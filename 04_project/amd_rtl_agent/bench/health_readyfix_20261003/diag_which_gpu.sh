#!/bin/bash
# 确定我们的模型服务实际用哪块 GPU
echo "=== llama-server 持有的 DRM 节点 ==="
PID=$(pgrep -f "llama-server -m" | head -1)
echo "  PID=$PID"
ls -l /proc/$PID/fd 2>/dev/null | grep -E "dri|kfd" | sed 's/^/    /'

echo
echo "=== renderD* 到 card* 的映射 ==="
for r in /sys/class/drm/renderD*; do
  b=$(basename "$r")
  dev="$r/device"
  [ -e "$dev" ] || continue
  pci=$(grep -m1 PCI_SLOT_NAME "$dev/uevent" 2>/dev/null | cut -d= -f2)
  # 找到同 PCI 的 card
  card=""
  for c in /sys/class/drm/card[0-9]*/device; do
    cc=$(grep -m1 PCI_SLOT_NAME "$c/uevent" 2>/dev/null | cut -d= -f2)
    [ "$cc" = "$pci" ] && card=$(basename $(dirname "$c"))
  done
  f="$dev/mem_info_vram_used"
  used=""
  [ -f "$f" ] && used=$(python3 -c "print('%.3f GB' % ($(cat $f)/1024**3))" 2>/dev/null)
  printf "  %-12s PCI=%-14s -> card=%-8s VRAM_used=%s\n" "$b" "${pci:-?}" "${card:-?}" "${used:-?}"
done

echo
echo "=== 我们的模型服务用的那块，显存占用 ==="
NODE=$(ls -l /proc/$PID/fd 2>/dev/null | grep -oE "renderD[0-9]+" | head -1)
echo "  节点: $NODE"
if [ -n "$NODE" ]; then
  PCI=$(grep -m1 PCI_SLOT_NAME /sys/class/drm/$NODE/device/uevent 2>/dev/null | cut -d= -f2)
  echo "  PCI : $PCI"
  for c in /sys/class/drm/card[0-9]*/device; do
    cc=$(grep -m1 PCI_SLOT_NAME "$c/uevent" 2>/dev/null | cut -d= -f2)
    if [ "$cc" = "$PCI" ]; then
      f="$c/mem_info_vram_used"
      echo "  对应 card: $(basename $(dirname $c))"
      [ -f "$f" ] && python3 -c "print('  我们的显存占用: %.3f GB' % ($(cat $f)/1024**3))"
    fi
  done
fi

echo
echo "=== 对照：全部 AMD 卡合计 vs 最大单卡 ==="
python3 - <<'PYEOF'
import glob, os
tot, mx, mxname = 0, 0, None
for c in sorted(glob.glob('/sys/class/drm/card[0-9]*/device')):
    try:
        if open(c + '/vendor').read().strip() != '0x1002':
            continue
        v = int(open(c + '/mem_info_vram_used').read().strip())
    except Exception:
        continue
    tot += v
    if v > mx:
        mx, mxname = v, os.path.basename(os.path.dirname(c))
print('  合计: %.3f GB' % (tot / 1024**3))
print('  最大单卡: %.3f GB (%s)' % (mx / 1024**3, mxname))
print('  当前 runtime 报的是【合计】= 67.4 GB -> 超过 32 的限制')
PYEOF
