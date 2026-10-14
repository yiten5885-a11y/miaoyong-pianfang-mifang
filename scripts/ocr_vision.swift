// ocr_vision.swift
// macOS Vision framework OCR for scanned PDF pages.
// Usage: ocr_vision <pdf-path> <start-page-1based> <end-page-1based> <out.jsonl>
import Foundation
import Vision
import PDFKit
import CoreGraphics
import AppKit

struct Line: Codable {
    let text: String
    let x: Double
    let y: Double
    let w: Double
    let h: Double
    let conf: Double
}
struct PageResult: Codable {
    let page: Int
    let width: Double
    let height: Double
    let lines: [Line]
}

func renderPage(_ page: PDFPage, scale: CGFloat) -> CGImage? {
    let bounds = page.bounds(for: .mediaBox)
    let w = Int(bounds.width * scale)
    let h = Int(bounds.height * scale)
    guard w > 0, h > 0 else { return nil }
    guard let ctx = CGContext(data: nil, width: w, height: h,
                              bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: scale, y: scale)
    ctx.translateBy(x: -bounds.origin.x, y: -bounds.origin.y)
    page.draw(with: .mediaBox, to: ctx)
    return ctx.makeImage()
}

func ocr(_ cg: CGImage) -> [Line] {
    var out: [Line] = []
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["zh-Hans", "en-US"]
    req.usesLanguageCorrection = true
    if #available(macOS 13.0, *) {
        req.revision = VNRecognizeTextRequestRevision3
    }
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([req]) } catch { return out }
    guard let obs = req.results else { return out }
    for o in obs {
        guard let top = o.topCandidates(1).first else { continue }
        let bb = o.boundingBox
        out.append(Line(text: top.string, x: Double(bb.origin.x), y: Double(bb.origin.y),
                        w: Double(bb.size.width), h: Double(bb.size.height),
                        conf: Double(top.confidence)))
    }
    return out
}

let args = CommandLine.arguments
guard args.count >= 5 else {
    FileHandle.standardError.write("usage: ocr_vision <pdf> <start> <end> <out.jsonl>\n".data(using: .utf8)!)
    exit(1)
}
let pdfPath = args[1]
let start = Int(args[2]) ?? 1
let end = Int(args[3]) ?? 1
let outPath = args[4]

guard let doc = PDFDocument(url: URL(fileURLWithPath: pdfPath)) else {
    FileHandle.standardError.write("cannot open pdf\n".data(using: .utf8)!)
    exit(2)
}

FileManager.default.createFile(atPath: outPath, contents: nil)
guard let fh = FileHandle(forWritingAtPath: outPath) else { exit(3) }
let enc = JSONEncoder()

let scale: CGFloat = args.count >= 6 ? CGFloat(Double(args[5]) ?? 2.6) : 2.6
for i in start...end {
    autoreleasepool {
        guard i - 1 < doc.pageCount, let page = doc.page(at: i - 1) else { return }
        let bounds = page.bounds(for: .mediaBox)
        var lines: [Line] = []
        if let cg = renderPage(page, scale: scale) {
            lines = ocr(cg)
        }
        let pr = PageResult(page: i, width: Double(bounds.width), height: Double(bounds.height), lines: lines)
        if let data = try? enc.encode(pr) {
            fh.write(data)
            fh.write("\n".data(using: .utf8)!)
        }
        FileHandle.standardError.write("page \(i) lines=\(lines.count)\n".data(using: .utf8)!)
    }
}
try? fh.close()
