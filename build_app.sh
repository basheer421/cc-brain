#!/bin/bash
# Build CC Brain.app macOS application bundle

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="CC Brain"
APP_DIR="$SCRIPT_DIR/dist/${APP_NAME}.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

echo "Building ${APP_NAME}.app..."

# Clean previous build
rm -rf "$APP_DIR"

# Create bundle structure
mkdir -p "$MACOS"
mkdir -p "$RESOURCES"

# Copy Python source
cp -r "$SCRIPT_DIR/cc_brain" "$RESOURCES/cc_brain"

# Copy icons
cp -r "$SCRIPT_DIR/icons" "$RESOURCES/icons"

# Portable launcher: bash wrapper execs into python so the Python process
# becomes PID 1 of the app and gets the WindowServer connection for menu bar.
# No hardcoded python path — works on any machine with python3 in PATH.
cat > "$MACOS/cc-brain" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
# Resolve real python binary (skip pyenv shims which break Finder launches)
PYTHON="$(python3 -c 'import sys; print(sys.executable)' 2>/dev/null || echo /usr/local/bin/python3)"
exec "$PYTHON" "$DIR/../Resources/cc-brain-launcher.py" "$@"
LAUNCHER

cat > "$RESOURCES/cc-brain-launcher.py" << 'PYLAUNCH'
import os
import sys
import fcntl

lock_path = os.path.expanduser("~/.cc-brain/.lock")
os.makedirs(os.path.dirname(lock_path), exist_ok=True)
lock_file = open(lock_path, "w")
try:
    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    sys.exit(0)

resources = os.path.join(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, resources)

import cc_brain.app as app
from pathlib import Path
app.ICONS_DIR = Path(resources) / "icons"

from cc_brain.app import main
main()
PYLAUNCH

chmod +x "$MACOS/cc-brain"

# Create Info.plist
cat > "$CONTENTS/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>CC Brain</string>
  <key>CFBundleDisplayName</key>
  <string>CC Brain</string>
  <key>CFBundleIdentifier</key>
  <string>io.ccbrain.app</string>
  <key>CFBundleVersion</key>
  <string>0.1.0</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleExecutable</key>
  <string>cc-brain</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>LSUIElement</key>
  <true/>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>LSApplicationCategoryType</key>
  <string>public.app-category.developer-tools</string>
</dict>
</plist>
PLIST

# Generate app icon (icns) from the brain icon
# Create a 512x512 version for the app icon
"$(python3 -c 'import sys; print(sys.executable)')" -c "
from PIL import Image, ImageDraw
import subprocess, os, tempfile

# Generate a larger brain icon for the app
size = 512
scale = 4
big = size * scale
from PIL import Image, ImageDraw
canvas = Image.new('RGBA', (big, big), (0, 0, 0, 0))
d = ImageDraw.Draw(canvas)

cx, cy = big / 2, big * 0.46
s = big * 0.40

d.ellipse([cx - s*1.05, cy - s*1.0, cx + s*0.1, cy + s*0.3], fill=(50, 50, 50, 255))
d.ellipse([cx - s*0.1, cy - s*1.0, cx + s*1.05, cy + s*0.3], fill=(50, 50, 50, 255))
d.ellipse([cx - s*0.85, cy - s*0.15, cx + s*0.08, cy + s*0.85], fill=(50, 50, 50, 255))
d.ellipse([cx - s*0.08, cy - s*0.15, cx + s*0.85, cy + s*0.85], fill=(50, 50, 50, 255))

stem_w = s * 0.22
stem_top = cy + s * 0.55
stem_bot = cy + s * 1.15
d.polygon([(cx - stem_w, stem_top), (cx + stem_w, stem_top),
           (cx + stem_w * 0.4, stem_bot), (cx - stem_w * 0.4, stem_bot)], fill=(50, 50, 50, 255))

lw = max(2, round(big / 12))
clear = (0, 0, 0, 0)
d.line([cx, cy - s*0.85, cx, cy + s*0.5], fill=clear, width=lw)

fold_cx = cx - s * 0.45
fold_cy = cy - s * 0.05
d.arc([fold_cx - s*0.35, fold_cy - s*0.25, fold_cx + s*0.35, fold_cy + s*0.25],
      start=20, end=160, fill=clear, width=lw)

fold_cx = cx + s * 0.45
d.arc([fold_cx - s*0.35, fold_cy - s*0.25, fold_cx + s*0.35, fold_cy + s*0.25],
      start=20, end=160, fill=clear, width=lw)

canvas = canvas.resize((size, size), Image.LANCZOS)

# Save as PNG then convert to icns
iconset = '$RESOURCES/AppIcon.iconset'
os.makedirs(iconset, exist_ok=True)

for s, name in [(16,'icon_16x16'), (32,'icon_16x16@2x'), (32,'icon_32x32'),
                (64,'icon_32x32@2x'), (128,'icon_128x128'), (256,'icon_128x128@2x'),
                (256,'icon_256x256'), (512,'icon_256x256@2x'), (512,'icon_512x512')]:
    canvas.resize((s, s), Image.LANCZOS).save(f'{iconset}/{name}.png')

subprocess.run(['iconutil', '-c', 'icns', iconset, '-o', '$RESOURCES/AppIcon.icns'], check=True)
import shutil
shutil.rmtree(iconset)
print('App icon created.')
"

echo ""
echo "✓ Built: $APP_DIR"
echo ""
echo "To install:"
echo "  cp -r \"$APP_DIR\" /Applications/"
echo ""
echo "Or run directly:"
echo "  open \"$APP_DIR\""
