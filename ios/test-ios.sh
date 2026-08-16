#!/bin/bash
# test-ios.sh — draait de tests en zet alle schermafdrukken in _tests/.
#
# Waarom apart van `xcodebuild test`: de rooktests maken platen (een pagina in
# de lezer, een epub-hoofdstuk, kleur mét vertaling) en die verdwijnen anders in
# een resultbundle waar niemand in kijkt. Ze horen ergens te staan waar Daniel
# ze gewoon kan openen.
#
#   ./test-ios.sh            unittests + rooktests
#   ./test-ios.sh unit       alleen de unittests (geen NAS nodig)
set -e
cd "$(dirname "$0")"

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SCHEME="BookPal"
PROJECT="BookPal.xcodeproj"
PLATEN="../_tests"
SIM="${BOOKPAL_SIM:-iPhone 17 Pro}"

xcodegen generate >/dev/null

echo "→ Unittests…"
xcodebuild test -project "$PROJECT" -scheme "$SCHEME" \
    -destination "platform=iOS Simulator,name=$SIM" \
    -derivedDataPath build/DerivedData \
    -only-testing:BookPalTests 2>&1 | grep -E "✘|Test run with|TEST (SUCCEEDED|FAILED)" || true

if [ "$1" = "unit" ]; then exit 0; fi

echo "→ Rooktests tegen de NAS…"
BUNDLE=$(mktemp -d)/rook.xcresult
xcodebuild test -project "$PROJECT" -scheme "$SCHEME" \
    -destination "platform=iOS Simulator,name=$SIM" \
    -derivedDataPath build/DerivedData \
    -only-testing:BookPalUITests \
    -resultBundlePath "$BUNDLE" 2>&1 \
    | grep -E "Test Case.*(passed|failed|skipped)|TEST (SUCCEEDED|FAILED)" || true

echo "→ Schermafdrukken bewaren…"
mkdir -p "$PLATEN"
UIT=$(mktemp -d)
xcrun xcresulttool export attachments --path "$BUNDLE" --output-path "$UIT" >/dev/null 2>&1 || true

# De manifest koppelt de bestandsnaam aan de naam die de test meegaf; zonder dat
# krijg je een map met UUID's waar je niets aan hebt.
python3 - "$UIT" "$PLATEN" <<'PY'
import json, shutil, sys
from pathlib import Path

uit, doel = Path(sys.argv[1]), Path(sys.argv[2])
manifest = uit / "manifest.json"
if not manifest.exists():
    print("   (geen platen gevonden)")
    raise SystemExit

gevonden = 0
def loop(node):
    global gevonden
    if isinstance(node, dict):
        naam = str(node.get("suggestedHumanReadableName", ""))
        bestand = node.get("exportedFileName", "")
        # Alleen wat een test zelf een naam gaf; de automatische UI-snapshots
        # van XCTest zijn er honderden en zeggen niets.
        if bestand and naam and not naam.startswith(("UI Snapshot", "Synthesized", "kXC")):
            kaal = naam.split("_")[0]
            bron = uit / bestand
            if bron.exists():
                shutil.copy(bron, doel / f"ios-{kaal}{bron.suffix}")
                print(f"   {kaal}")
                gevonden += 1
        for waarde in node.values():
            loop(waarde)
    elif isinstance(node, list):
        for waarde in node:
            loop(waarde)

loop(json.load(open(manifest)))
if gevonden == 0:
    print("   (geen benoemde platen)")
PY

echo "✓ Klaar. De platen staan in $(cd "$PLATEN" && pwd)."
