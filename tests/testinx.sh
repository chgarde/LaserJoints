#!/bin/bash
# opens an inkscape extension settings window and takes a screenshot.
# useful when designing inx files.
# dependencies : imagemagick, xdotool
#
# limitations: 
# - no interaction possible, it's in shell mode...
# - with notebooks, only first tab will be shown, workaround=comment other tabs in inx file.
#
# example applied to https://gitlab.com/inkscape/extensions/-/blob/master/color_blackandwhite.inx?ref_type=heads

# EXTENSION="org.inkscape.color.black_and_white" # matches the <id> of the INX file (replace _ with -)
# WINDOW_NAME="Black and White" # matches the <Name> of the INX file
EXTENSION=org.inkscape.filter.laserjoints # matches the <id> of the INX file (replace _ with -)
WINDOW_NAME=LaserJoint # matches the <Name> of the INX file

EXTENSION=${EXTENSION//_/-}
f=/tmp/inx_screnshot.png
rm -f "$f"

(
    # commands here will be passed to inkscape shell
    echo $EXTENSION;

    # Wait for Inkscape window to appear
    while ! xdotool search --name "$WINDOW_NAME" >/dev/null; do
        sleep 1
    done
    sleep 2
    import -window  "$WINDOW_NAME" "$f"

) | inkscape -g --shell

# display the screenshot, here relying on imagemagick
display "$f"