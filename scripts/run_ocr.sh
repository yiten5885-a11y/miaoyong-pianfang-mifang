#!/bin/bash
# Parallel OCR driver: splits the page range across N workers.
# usage: run_ocr.sh <pdf> <first-page> <last-page> <workers> <outdir>
set -u
PDF="$1"; FIRST="$2"; LAST="$3"; WORKERS="${4:-6}"; OUTDIR="$5"; SCALE="${6:-2.2}"
mkdir -p "$OUTDIR"
TOTAL=$(( LAST - FIRST + 1 ))
CHUNK=$(( (TOTAL + WORKERS - 1) / WORKERS ))
PIDS=()
for (( w=0; w<WORKERS; w++ )); do
  S=$(( FIRST + w*CHUNK ))
  E=$(( S + CHUNK - 1 ))
  [ "$E" -gt "$LAST" ] && E="$LAST"
  [ "$S" -gt "$LAST" ] && continue
  /tmp/ocr_vision "$PDF" "$S" "$E" "$OUTDIR/part_${w}.jsonl" "$SCALE" 2>"$OUTDIR/part_${w}.log" &
  PIDS+=($!)
done
FAIL=0
for p in "${PIDS[@]}"; do
  wait "$p" || FAIL=1
done
echo "workers_done fail=$FAIL"
wc -l "$OUTDIR"/part_*.jsonl
