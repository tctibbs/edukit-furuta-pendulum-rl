#!/usr/bin/env bash
# Convert a recorder mp4 into a GIF for an experiment write-up.
#
# The recorder writes one frame per 2 ms control step, but usually draws only every
# other one and leaves the rest blank. Keep the drawn frames, restamp them to the rate
# of simulated time they stand for, then resample to the output rate. Getting either
# step wrong has happened: keeping the blank half produces an all-black GIF, and
# restamping wrongly plays back at the wrong speed.
#
# Which frames are blank is NOT stable between recordings. Three recordings of the same
# script in this project produced odd blank, even blank, and none blank. So the parity
# is detected per file by scripts/frame_parity.sh rather than assumed. Pass it
# explicitly only to override that.
#
# Usage: video_to_gif.sh <in.mp4> <out.gif> [fps] [width] [start_s] [duration_s] [parity] [crop] [colours] [dither]
#
#   fps        output frame rate, default 25 (experiment 05's rate)
#   width      output width in pixels, default 430 (height follows the aspect)
#   start_s    seconds of simulated time to skip, default 0
#   duration_s seconds of simulated time to keep, default the whole clip
#   parity     which frames are drawn: `auto` (default), `odd`, `even` or `all`
#   crop       ffmpeg crop applied before scaling, as `w:h:x:y`, or `none` (default).
#              The renderer frames a whole ground plane around a small rig, so cropping
#              to the part that moves is usually most of the file size.
#   colours    palette size, default 256. These renders are grey on grey, and 64 is
#              more than the scene contains.
#   dither     `bayer` (default) or `none`. Dithering a smooth grey gradient sprays it
#              with noise the GIF then has to store; on one pair, 64 colours with no
#              dither was 1.0 MB against 1.5.
#
# fps must be one GIF can store exactly, meaning 100/fps is a whole number of
# centiseconds. 25, 20, 12.5 and 10 are the useful ones; anything else is refused.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=scripts/gif_lib.sh
source "$here/gif_lib.sh"

in=$1
out=$2
fps=${3:-25}
width=${4:-430}
start=${5:-0}
duration=${6:-}
parity=${7:-auto}
crop=${8:-none}
colours=${9:-256}
dither=${10:-bayer}

require_exact_fps "$fps"

cropf=""
if [[ "$crop" != "none" ]]; then
    if [[ ! "$crop" =~ ^[0-9]+:[0-9]+:[0-9]+:[0-9]+$ ]]; then
        echo "crop must be w:h:x:y, got '$crop'" >&2; exit 2
    fi
    cropf="crop=${crop},"
fi
case "$dither" in
    bayer) ditherf="dither=bayer:bayer_scale=3" ;;
    none)  ditherf="dither=none" ;;
    *) echo "dither must be bayer or none, got '$dither'" >&2; exit 2 ;;
esac

if [[ "$parity" == "auto" ]]; then
    parity=$("$here/frame_parity.sh" "$in")
    echo "$(basename "$in"): drawn frames are '$parity'"
fi

keep=$(parity_filter "$parity")

trim=""
if [[ -n "$duration" ]]; then
    trim="trim=start=${start}:duration=${duration},setpts=PTS-STARTPTS,"
elif [[ "$start" != "0" ]]; then
    trim="trim=start=${start},setpts=PTS-STARTPTS,"
fi

# Palette in the same graph: GIF is 256 colours per palette, and a palette built from
# the clip itself avoids the banding a generic one produces on the grey background.
ffmpeg -y -loglevel error -i "$in" -vf "\
${keep}${trim}${cropf}\
fps=${fps},scale=${width}:-2:flags=lanczos,\
split[a][b];[a]palettegen=max_colors=${colours}:stats_mode=diff[p];[b][p]paletteuse=${ditherf}" \
    -loop 0 "$out"

report_gif "$out"
