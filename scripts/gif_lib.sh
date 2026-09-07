#!/usr/bin/env bash
# Shared pieces for the GIF builders. Source it, do not run it.
#
# Two things about the recorder and about GIF cost real time to rediscover, and both
# produce a file that looks plausible and plays wrong. They live here so the two build
# scripts cannot disagree about them.

# GIF stores a frame delay as a whole number of centiseconds. A frame rate whose period
# is not a whole number of centiseconds cannot be represented, so ffmpeg writes alternating
# delays that average out: at 12 fps it writes 8, 9, 8, 8, 9, and the clip judders even
# though its total duration is right. Fail rather than ship that.
require_exact_fps() {
    local fps=$1
    python3 - "$fps" <<'PY'
import sys
fps = float(sys.argv[1])
cs = 100.0 / fps
if abs(cs - round(cs)) < 1e-9:
    sys.exit(0)
exact = [100 / k for k in range(1, 26)]
near = sorted(exact, key=lambda v: abs(v - fps))[:3]
shown = ", ".join(f"{v:g}" for v in sorted(near))
print(
    f"fps {fps:g} needs {cs:.4f} centiseconds per frame, which GIF cannot store.\n"
    f"ffmpeg would alternate delays and the clip would judder.\n"
    f"Use one of: {shown}   (any 100/k is exact; 25, 20, 12.5 and 10 are the useful ones)",
    file=sys.stderr,
)
sys.exit(2)
PY
}

# The recorder writes one frame per control step but often draws only every other one,
# leaving the rest blank. Which half is blank is NOT stable between recordings: three
# recordings of one script in this project gave odd blank, even blank, and none blank.
# So the parity is detected per file, and the restamp rate follows from it. A clip with
# every frame drawn carries one frame per 2 ms control step, so its simulated time runs
# at 500 fps; dropping half of one halves that to 250.
parity_filter() {
    local parity=$1
    case "$parity" in
        odd)  echo "select='mod(n,2)',setpts=N/(250*TB)," ;;
        even) echo "select='not(mod(n,2))',setpts=N/(250*TB)," ;;
        all)  echo "setpts=N/(500*TB)," ;;
        *) echo "parity must be auto, odd, even or all, got '$parity'" >&2; return 2 ;;
    esac
}

# Report what the file actually plays at, so a wrong one is caught at build time rather
# than by someone watching it later.
report_gif() {
    local out=$1
    local dur delays
    dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out")
    delays=$(ffprobe -v error -select_streams v -show_entries frame=duration_time \
        -of csv=p=0 "$out" | sort -u | tr '\n' ' ')
    echo "$(basename "$out"): $(du -h "$out" | cut -f1)" \
         "$(ffprobe -v error -select_streams v -show_entries stream=width,height,nb_frames -of csv=p=0 "$out")" \
         "plays ${dur}s, frame delays: ${delays}"
}
