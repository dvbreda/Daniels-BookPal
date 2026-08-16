#!/bin/bash
# deploy-ios.sh — genereert, bouwt en installeert BookPal op een verbonden iPhone.
#
# Dezelfde opzet als bij Daniels Plantpal, bewust: één script per project dat je
# op dezelfde manier aanroept scheelt onthouden. Draadloos werkt zodra "Connect
# via Network" voor het toestel aanstaat (Xcode → Window → Devices and Simulators).
set -e
cd "$(dirname "$0")"

export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

SCHEME="BookPal"
PROJECT="BookPal.xcodeproj"
ZOEK="${1:-Daniel}"   # welk toestel; standaard dat van Daniel

# ── 1. Toestel zoeken ─────────────────────────────────────────────────────────
echo "→ iPhone zoeken..."
DEVICE_LINE=$(xcrun xctrace list devices 2>/dev/null \
    | grep -i "iphone" | grep -v "Simulator" | grep -i "$ZOEK" | head -1)
if [ -z "$DEVICE_LINE" ]; then
    DEVICE_LINE=$(xcrun xctrace list devices 2>/dev/null \
        | grep -i "iphone" | grep -v "Simulator" | head -1)
fi
if [ -z "$DEVICE_LINE" ]; then
    echo "✗ Geen iPhone gevonden."
    echo "  Draadloos: zet 'Connect via Network' aan via Xcode → Window → Devices."
    echo "  Bedraad: sluit hem aan en vertrouw deze Mac."
    exit 1
fi

DEVICE_NAME=$(echo "$DEVICE_LINE" | sed 's/ ([^)]*) ([^)]*)//')
DEVICE_ID=$(echo "$DEVICE_LINE" | grep -oE '\(?[0-9a-fA-F]{8}-[0-9a-fA-F]+\)?' | tail -1 | tr -d '()')
echo "✓ $DEVICE_NAME ($DEVICE_ID)"

# ── 2. Project genereren ──────────────────────────────────────────────────────
echo "→ Project genereren (XcodeGen)..."
if ! command -v xcodegen >/dev/null 2>&1; then
    echo "✗ XcodeGen niet gevonden. Installeer met: brew install xcodegen"
    exit 1
fi
xcodegen generate >/dev/null

# ── 3. Bouwen ─────────────────────────────────────────────────────────────────
echo "→ Bouwen voor het toestel (kan even duren)..."
BUILD_LOG=$(mktemp)
# -allowProvisioningUpdates: het wildcard-profiel op nl.danielvanbreda.* dekt
# deze bundle-id al, maar een nieuw toestel moet er nog aan toegevoegd kunnen
# worden zonder dat je het portaal in hoeft.
xcodebuild \
    -project "$PROJECT" \
    -scheme "$SCHEME" \
    -configuration Debug \
    -destination "platform=iOS,id=$DEVICE_ID" \
    -derivedDataPath build/DerivedData \
    -allowProvisioningUpdates \
    build > "$BUILD_LOG" 2>&1 || true

grep -E "error:|BUILD" "$BUILD_LOG" | grep -v "^warning" || true
if ! grep -q "BUILD SUCCEEDED" "$BUILD_LOG"; then
    echo ""
    echo "✗ Build mislukt. Laatste regels:"
    tail -30 "$BUILD_LOG"
    rm "$BUILD_LOG"
    exit 1
fi
rm "$BUILD_LOG"

# ── 4. Installeren ────────────────────────────────────────────────────────────
echo "→ Installeren op $DEVICE_NAME..."
APP_PATH=$(find build/DerivedData -name "$SCHEME.app" -path "*/Debug-iphoneos/*" 2>/dev/null | head -1)
if [ -z "$APP_PATH" ]; then
    echo "✗ $SCHEME.app niet gevonden na de build"
    exit 1
fi

xcrun devicectl device install app --device "$DEVICE_ID" "$APP_PATH"

echo ""
echo "✓ BookPal staat op $DEVICE_NAME."
