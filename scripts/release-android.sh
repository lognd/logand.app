#!/usr/bin/env bash
# Cut an Android release: bump versionCode + versionName in
# android/app/build.gradle.kts, commit, tag vX.Y.Z, and push the tag.
#
# Pushing a v* tag is what triggers .github/workflows/release-android.yml,
# which builds the signed APK and attaches it to a GitHub Release. The
# in-app updater compares that tag against BuildConfig.VERSION_NAME, so
# versionName MUST match the tag or every install nags "update available"
# forever; versionCode MUST strictly increase or Android refuses the
# install over an existing one. This script keeps all three in lockstep so
# they can never drift.
#
# Usage:
#   scripts/release-android.sh 1.2.0          # bump, commit, tag -- prints the push command
#   scripts/release-android.sh 1.2.0 --push   # ...and push the tag (triggers the release)
#
# Safe by default: without --push nothing leaves your machine, so you can
# inspect the commit and tag first and `git reset --hard HEAD~1 && git tag
# -d vX.Y.Z` to undo.
set -euo pipefail

GRADLE_FILE="android/app/build.gradle.kts"

die() { echo "error: $*" >&2; exit 1; }

# --- resolve repo root so the script works from anywhere -------------------
cd "$(git rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git repository"
[ -f "$GRADLE_FILE" ] || die "$GRADLE_FILE not found -- run from the logand.app repo"

# --- args ------------------------------------------------------------------
VERSION="${1:-}"
PUSH="no"
[ "${2:-}" = "--push" ] && PUSH="yes"
[ -n "$VERSION" ] || die "usage: scripts/release-android.sh X.Y.Z [--push]"

# Strict semver MAJOR.MINOR.PATCH -- the tag and versionName both use it.
echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' \
  || die "version must be MAJOR.MINOR.PATCH (e.g. 1.2.0), got '$VERSION'"
TAG="v$VERSION"

# --- preconditions: clean tree, on a branch, tag not taken -----------------
git diff --quiet && git diff --cached --quiet \
  || die "working tree is dirty -- commit or stash first (a release must be reproducible from a clean tree)"
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null \
  && die "tag $TAG already exists -- pick a new version or delete it with 'git tag -d $TAG'"

# --- read current values ---------------------------------------------------
CUR_CODE="$(grep -oE 'versionCode = [0-9]+' "$GRADLE_FILE" | grep -oE '[0-9]+')"
CUR_NAME="$(grep -oE 'versionName = "[^"]+"' "$GRADLE_FILE" | sed -E 's/.*"([^"]+)".*/\1/')"
[ -n "$CUR_CODE" ] && [ -n "$CUR_NAME" ] || die "could not parse current versionCode/versionName from $GRADLE_FILE"

# --- new version must be strictly greater (both fields) --------------------
# versionName ordering via `sort -V`; reject equal or lower.
if [ "$VERSION" = "$CUR_NAME" ]; then
  die "versionName is already $CUR_NAME -- pick a higher version"
fi
HIGHEST="$(printf '%s\n%s\n' "$CUR_NAME" "$VERSION" | sort -V | tail -1)"
[ "$HIGHEST" = "$VERSION" ] || die "version $VERSION is lower than current $CUR_NAME -- releases only go forward"
NEW_CODE=$((CUR_CODE + 1))

echo "Android release:"
echo "  versionName  $CUR_NAME  ->  $VERSION"
echo "  versionCode  $CUR_CODE  ->  $NEW_CODE"
echo "  tag          $TAG"
echo

# --- apply the bump --------------------------------------------------------
# No end-of-line ($) anchor: the working tree may have CRLF endings (git
# autocrlf), and a trailing \r sits between the value and the line end, so
# `... = 2$` would never match. Each key appears once in the file, so
# matching the key plus its value shape is specific enough.
sed -i -E "s/versionCode = [0-9]+/versionCode = $NEW_CODE/" "$GRADLE_FILE"
sed -i -E "s/versionName = \"[^\"]+\"/versionName = \"$VERSION\"/" "$GRADLE_FILE"

# Verify the edit actually took (a silent no-op sed would tag a stale build).
grep -q "versionCode = $NEW_CODE" "$GRADLE_FILE" || die "failed to update versionCode"
grep -q "versionName = \"$VERSION\"" "$GRADLE_FILE" || die "failed to update versionName"

git add "$GRADLE_FILE"
git commit -q -m "chore(android): release $TAG"
git tag -a "$TAG" -m "Android release $TAG"

if [ "$PUSH" = "yes" ]; then
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  echo "Pushing branch $BRANCH and tag $TAG (this triggers the release build)..."
  git push origin "$BRANCH"
  git push origin "$TAG"
  echo "Done. Watch it with: gh run list --workflow 'Release Android'"
else
  echo "Committed and tagged locally. Nothing pushed."
  echo "To release, push both the commit and the tag:"
  echo "    git push origin HEAD && git push origin $TAG"
  echo "Or re-run with --push. To undo:"
  echo "    git tag -d $TAG && git reset --hard HEAD~1"
fi
