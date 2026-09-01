#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${CANONICAL_OCI_BASE_URL:-https://partner-images.canonical.com/oci/jammy/current}"
ROOTFS_NAME="ubuntu-jammy-oci-amd64-root.tar.gz"
IMAGE_TAG="${IMAGE_TAG:-amd-rtl-local/ubuntu:22.04}"

for command_name in curl sha256sum docker; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        echo "missing required command: ${command_name}" >&2
        exit 1
    fi
done

work_dir="$(mktemp -d)"
trap 'rm -rf -- "${work_dir}"' EXIT

checksums_path="${work_dir}/SHA256SUMS"
rootfs_path="${work_dir}/${ROOTFS_NAME}"

echo "Downloading Canonical checksum list..."
curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
    --output "${checksums_path}" \
    "${BASE_URL}/SHA256SUMS"

expected_sha="$(awk -v filename="*${ROOTFS_NAME}" '$2 == filename { print $1; exit }' "${checksums_path}")"
if [[ ! "${expected_sha}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "checksum for ${ROOTFS_NAME} was not found in Canonical SHA256SUMS" >&2
    exit 1
fi

echo "Downloading Canonical Ubuntu 22.04 OCI rootfs..."
curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
    --output "${rootfs_path}" \
    "${BASE_URL}/${ROOTFS_NAME}"

echo "${expected_sha}  ${rootfs_path}" | sha256sum --check --strict -

echo "Importing ${IMAGE_TAG}..."
docker import \
    --platform linux/amd64 \
    --change "LABEL org.opencontainers.image.source=${BASE_URL}/${ROOTFS_NAME}" \
    --change "LABEL org.opencontainers.image.version=22.04" \
    "${rootfs_path}" "${IMAGE_TAG}" >/dev/null

docker image inspect \
    --format 'image={{.RepoTags}} architecture={{.Architecture}} os={{.Os}} id={{.Id}}' \
    "${IMAGE_TAG}"

docker run --rm --network none "${IMAGE_TAG}" /bin/sh -eu -c '
    . /etc/os-release
    test "${ID}" = "ubuntu"
    test "${VERSION_ID}" = "22.04"
    printf "container_smoke=PASS id=%s version=%s\n" "${ID}" "${VERSION_ID}"
'

echo "base_image_bootstrap=PASS tag=${IMAGE_TAG} sha256=${expected_sha}"
