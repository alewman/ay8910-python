#!/bin/sh
# Build the referees from the pinned sources in reference/src/ (fetched by
# scripts/fetch_references.py, never committed here).
#
#   sh validation/build_referees.sh
#
# The binaries land in reference/build-referees/ (git-ignored). Nothing of the
# referees' sources is copied into this repository: validation/ay_tb.v and
# validation/ssg_ref.c only drive them.
#
# ay_ref needs Icarus Verilog (iverilog, vvp) on the PATH or under $OSS_CAD_SUITE/bin
# (the YosysHQ oss-cad-suite bundle has both). Icarus has no `trireg`, so the
# model is first copied with each trireg net given a keeper (validation/icarus_port.py).
#
# Licences: lvd's ay_model.v GPL-3.0+, Nuked's YM2203-LLE GPL-2.0+. Both are built
# locally and run as referees; neither is distributed.
set -e
root=$(cd "$(dirname "$0")/.." && pwd)
src="$root/reference/src"
out="$root/reference/build-referees"
mkdir -p "$out"
[ -n "$OSS_CAD_SUITE" ] && PATH="$OSS_CAD_SUITE/bin:$PATH"

CC=${CC:-gcc}
CFLAGS=${CFLAGS:--O2 -w}
PYTHON=${PYTHON:-python3}

echo "ay_ref   (lvd2/ay-3-8910_reverse_engineered @ cf8d14d, under Icarus Verilog)"
vvp -V 2>&1 | head -n 1
"$PYTHON" "$root/validation/icarus_port.py" \
    "$src/ay-3-8910_reverse_engineered/rtl/ay_model.v" "$out/ay_model_icarus.v"
iverilog -g2012 -o "$out/ay_ref" "$root/validation/ay_tb.v" "$out/ay_model_icarus.v" 2>&1 |
    grep -v "Anachronistic use of begin/end" || true

echo "ssg_ref  (nukeykt/YM2203-LLE @ 817387f)"
$CC --version | head -n 1
$CC $CFLAGS -I "$src/YM2203-LLE" -o "$out/ssg_ref" \
    "$root/validation/ssg_ref.c" "$src/YM2203-LLE/fmopn.c"

echo "built in $out"
