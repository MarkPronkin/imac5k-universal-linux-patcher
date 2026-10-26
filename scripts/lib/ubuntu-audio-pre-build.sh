#!/usr/bin/env bash
# Runs from the prepared DKMS tree. Never build an old ABI with newer sources.
set -euo pipefail
kernel=${1:?DKMS kernel release required}
[[ $kernel =~ ^[0-9]+\.[0-9]+\.[0-9]+-[0-9]+-generic$ ]] || {
    echo "Ubuntu audio requires an official generic/HWE kernel." >&2; exit 1;
}
package=linux-source-${kernel%%-*}
metadata=$(dpkg-query -W -f='${db:Status-Status} ${source:Package} ${source:Version}' "linux-headers-$kernel")
read -r status source version extra <<< "$metadata"
[[ $status == installed && -z $extra && $version =~ ^[0-9][a-zA-Z0-9.+:~_-]*$ &&
   ( $source == linux || $source =~ ^linux-hwe-[0-9]+\.[0-9]+$ ) ]] || {
    echo "Cannot identify official Ubuntu headers for $kernel." >&2; exit 1;
}
metadata=$(dpkg-query -W -f='${db:Status-Status} ${source:Package} ${source:Version}' "$package") || metadata=
[[ $metadata == "installed $source $version" ]] || {
    echo "Audio sources do not match $kernel. Install $package=$version before rebuilding DKMS." >&2
    exit 1
}
exec ./install.cirrus.driver.sh -k "$kernel" --dkms
