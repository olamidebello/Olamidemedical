#!/usr/bin/env bash
set -euo pipefail
umask 077
repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
sdk_dir=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}
[[ -n "$sdk_dir" ]] || { echo 'Set ANDROID_HOME to an Android SDK with platform 35 and build-tools 35.0.0.' >&2; exit 1; }
build_tools="$sdk_dir/build-tools/35.0.0"
android_jar="$sdk_dir/platforms/android-35/android.jar"
for tool in aapt d8 zipalign apksigner; do [[ -x "$build_tools/$tool" ]] || { echo "Missing $build_tools/$tool" >&2; exit 1; }; done
[[ -f "$android_jar" ]] || { echo 'Android platform 35 is required.' >&2; exit 1; }
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
signing_dir=${MEDICAL_SIGNING_DIR:-"$HOME/.local/share/olamidemedical-signing"}
mkdir -p "$signing_dir" "$repo_dir/static/downloads" "$work_dir/classes" "$work_dir/dex"
chmod 700 "$signing_dir"
if [[ ! -f "$signing_dir/release.jks" ]]; then
    [[ ! -e "$signing_dir/password" ]] || { echo 'Password exists without signing key; restore the matching key.' >&2; exit 1; }
    python3 -c 'import secrets,sys; open(sys.argv[1],"x").write(secrets.token_urlsafe(40))' "$signing_dir/password"
    keytool -genkeypair -keystore "$signing_dir/release.jks" -alias medical -keyalg RSA -keysize 3072 -validity 10000 \
      -storepass:file "$signing_dir/password" -keypass:file "$signing_dir/password" \
      -dname 'CN=Olamide Medical Android, O=Olamide Medical' >/dev/null
fi
[[ -r "$signing_dir/password" ]] || { echo 'Restore the signing password file.' >&2; exit 1; }
"$build_tools/aapt" package -f -M "$repo_dir/android/app/src/main/AndroidManifest.xml" \
    -S "$repo_dir/android/app/src/main/res" -I "$android_jar" -F "$work_dir/unsigned.apk"
javac -source 8 -target 8 -classpath "$android_jar" -d "$work_dir/classes" \
    "$repo_dir/android/app/src/main/java/health/olamidemedical/app/MainActivity.java"
mapfile -t class_files < <(find "$work_dir/classes" -name '*.class' -type f)
"$build_tools/d8" --min-api 26 --lib "$android_jar" --output "$work_dir/dex" "${class_files[@]}"
python3 - "$work_dir/unsigned.apk" "$work_dir/dex/classes.dex" <<'PY'
import sys,zipfile
with zipfile.ZipFile(sys.argv[1],'a',compression=zipfile.ZIP_DEFLATED) as apk: apk.write(sys.argv[2],'classes.dex')
PY
"$build_tools/zipalign" -p -f 4 "$work_dir/unsigned.apk" "$work_dir/aligned.apk"
"$build_tools/apksigner" sign --ks "$signing_dir/release.jks" --ks-key-alias medical \
    --ks-pass "file:$signing_dir/password" \
    --out "$work_dir/olamide-medical.apk" "$work_dir/aligned.apk"
"$build_tools/apksigner" verify --verbose "$work_dir/olamide-medical.apk"
install -m 0644 "$work_dir/olamide-medical.apk" "$repo_dir/static/downloads/olamide-medical.apk"
(cd "$repo_dir/static/downloads" && sha256sum olamide-medical.apk > olamide-medical.apk.sha256)
chmod 644 "$repo_dir/static/downloads/olamide-medical.apk.sha256"
echo 'Built static/downloads/olamide-medical.apk. Back up the external signing directory securely; updates must use the same key.'
