#!/usr/bin/env bash
# Verify that a tag push names an annotated final release of the package version.
set -euo pipefail

: "${GITHUB_REF:?}" "${GITHUB_REF_NAME:?}"

if [[ ! "$GITHUB_REF_NAME" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	echo "Release tags use the form vX.Y.Z: $GITHUB_REF_NAME" >&2
	exit 1
fi

version="$(uv version --package pymalloy --short)"
if [[ "v$version" != "$GITHUB_REF_NAME" ]]; then
	echo "pymalloy $version does not match tag $GITHUB_REF_NAME" >&2
	exit 1
fi

if [[ "$(git cat-file -t "$GITHUB_REF")" != tag ]]; then
	echo "Release tag $GITHUB_REF_NAME must be annotated" >&2
	exit 1
fi
