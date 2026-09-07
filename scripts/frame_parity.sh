#!/usr/bin/env bash
# Report which frames of a recorder mp4 carry a picture: `odd`, `even`, or `all`.
#
# The Isaac Lab recorder writes one frame per physics step but often draws only every
# other one, leaving the rest blank. Which half is blank is not stable: across three
# recordings of the same script this project has seen odd blank, even blank, and nothing
# blank. Guessing produces either an all-black GIF or one that plays at half speed, so
# the GIF tools ask this script rather than assume.
#
# Method: a blank frame is a flat colour, so it encodes to a tiny PNG. Extract a run of
# frames from the middle of the clip and compare the mean size of the even-indexed ones
# against the odd-indexed ones. A ratio past 4x is blanking; anything nearer than that is
# a clip where every frame was drawn.
#
# Usage: frame_parity.sh <in.mp4> [start_frame]
set -euo pipefail

in=$1
start=${2:-1000}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

ffmpeg -y -loglevel error -i "$in" \
    -vf "trim=start_frame=${start}:end_frame=$((start + 12))" -vsync 0 "$work/f_%d.png"

count=$(find "$work" -name 'f_*.png' | wc -l | tr -d ' ')
if [[ "$count" -lt 6 ]]; then
    echo "could not extract frames from $in near frame $start" >&2
    exit 1
fi

# f_1 is `start`, so odd-numbered files hold even frame indices.
even=0; even_n=0; odd=0; odd_n=0
for f in "$work"/f_*.png; do
    n=$(basename "$f" .png); n=${n#f_}
    size=$(wc -c < "$f")
    if (( n % 2 == 1 )); then even=$((even + size)); even_n=$((even_n + 1))
    else odd=$((odd + size)); odd_n=$((odd_n + 1)); fi
done
even=$((even / even_n)); odd=$((odd / odd_n))

# Report the half to KEEP, which is the half that carries the picture.
if (( even > odd * 4 )); then
    echo even
elif (( odd > even * 4 )); then
    echo odd
else
    echo all
fi
