#!/usr/bin/env bash
# Fetch the third-party reference document pack for the STEVAL-EDUKIT01.
#
# These files are copyright STMicroelectronics and Prof. William J. Kaiser, UCLA.
# They are not redistributed with this repository. This script pulls them from the
# original sources into docs/reference/, which is git-ignored.
#
# See docs/design-inputs/references/ for what each file is.

set -euo pipefail

DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docs/reference"
mkdir -p "$DEST"

UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'

fetch_drive() {
    local id="$1" out="$2"
    if [[ -s "$DEST/$out" ]]; then
        echo "skip  $out (already present)"
        return
    fi
    echo "get   $out"
    curl -sL --max-time 180 -A "$UA" \
        "https://drive.google.com/uc?export=download&id=${id}" -o "$DEST/$out"
}

# UCLA Edukit material, hosted on Google Drive from
# https://sites.google.com/view/ucla-st-motor-control/home
fetch_drive 1TShSZnhovXGBWyp9U5gxpYn494UExrGA Edukit_Manual.pdf
fetch_drive 1gxOZJ68nM6F8RLyT5_11yhetiQPhkdwl Serial_Interface_Guide.pdf
fetch_drive 1IK0jC-gvZcKVLdc7yAyQ-cKuVbFzp-tr RealTime_Workbench_Guide.pdf
fetch_drive 15bxHCpIVDkShvDSBV-TKK1VoyA9-v4Z1 Assembly_with_soldering.pdf
fetch_drive 1WjKFYuabeHYK_HCCIp5l3CJ5ZwTb3bSU Assembly_no_soldering.pdf
fetch_drive 1viemIrpEuDAfWZSLzvkyF_2NQqDRg5Az Install_Firmware.pdf
fetch_drive 1zVwDdAiL3QSQ81GxXas_2DFtwxWzJHig Edukit_firmware.bin
fetch_drive 1I-F9KUY2dun79LGVkVu25ZPb_Rtbx5q7 STM32CubeIDE_project.zip

# Author-provided MATLAB tools, same site, under "Edukit Resources". Not in the
# firmware and not in the manual's PDF text, only cited by name there (App. C).
fetch_drive 1raG4fgkm-hhJNN0D9wN2_U4Ju82m1CBq Edukit_Sensitivity_Function_Freq_Response_Computation_Matlab.m
fetch_drive 1cZBdpEbyfWLNI9O9VqDKLpZ8hpix6bSN Edukit_Full_State_Inverted_Mode_LQR_Design.m
fetch_drive 1kQNyseXgL4aANSITfvA1VX9_poVLBfxy Edukit_Full_State_Suspended_Mode_LQR_Design.m
fetch_drive 1NFEos3Fj_-pdDnN9VwzGfuVGvATUmKET Edukit_Full_State_Rotor_Design_with_LQR.m
fetch_drive 1-vutBoePbmHd-_na1OKTZvDiwcY6K-cf Edukit_Full_State_Performance_Measurement.m

cat <<'EOF'

Done for the UCLA material.

The official ST bill of materials (ST_BOM_v2.pdf) is not fetchable: st.com refuses
non-browser clients. Save it from the link below if the pack is being rebuilt from
scratch.

  https://www.st.com/resource/en/bill_of_materials/steval-edukit01_bom.pdf

Firmware source: https://github.com/wjkaiser/Edukit_Rotary_Inverted_Pendulum_Project
EOF
