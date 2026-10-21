/** A QR code drawn here as SVG squares: the link is never sent to anyone to draw. */
import { useMemo } from 'react';
import qrcode from 'qrcode-generator';

export function Qr({ text, label = "QR code for the food court's ordering page" }: { text: string; label?: string }) {
  const cells = useMemo(() => {
    const q = qrcode(0, 'M');
    q.addData(text);
    q.make();
    const n = q.getModuleCount();
    const dark: [number, number][] = [];
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (q.isDark(r, c)) dark.push([r, c]);
    return { n, dark };
  }, [text]);
  const quiet = 3;
  const size = cells.n + quiet * 2;
  return (
    <svg className="fc-qr" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} shapeRendering="crispEdges">
      <rect width={size} height={size} fill="#fff" />
      {cells.dark.map(([r, c]) => (
        <rect key={`${r}-${c}`} x={c + quiet} y={r + quiet} width="1" height="1" fill="#1b1530" />
      ))}
    </svg>
  );
}
