/** Shrink a phone photo before sending it: a bill needs 1600 pixels, not 12 megapixels. */

export const MAX_SIDE = 1600;
export const MAX_BYTES = 5 * 1024 * 1024;

/** The size to draw at: the long side at most MAX_SIDE, the shape kept. */
export function fitSize(w: number, h: number, max = MAX_SIDE): { w: number; h: number } {
  const longest = Math.max(w, h);
  if (longest <= max) return { w, h };
  const k = max / longest;
  return { w: Math.round(w * k), h: Math.round(h * k) };
}

const toBase64 = (buf: ArrayBuffer): string => {
  let s = '';
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};

/** A picture file as { base64, mediaType }, shrunk to a JPEG when the browser can. Null when it is
 * not a picture, or too big to send and impossible to shrink. */
export async function pictureForUpload(file: File): Promise<{ base64: string; mediaType: string } | null> {
  if (!file.type.startsWith('image/')) return null;
  try {
    const bmp = await createImageBitmap(file);
    const { w, h } = fitSize(bmp.width, bmp.height);
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d')?.drawImage(bmp, 0, 0, w, h);
    const blob = await new Promise<Blob | null>((ok) => canvas.toBlob(ok, 'image/jpeg', 0.82));
    if (blob && blob.size <= MAX_BYTES) return { base64: toBase64(await blob.arrayBuffer()), mediaType: 'image/jpeg' };
  } catch {
    /* an old browser, or a format it cannot draw: send the file as it is if it is small enough */
  }
  if (file.size > MAX_BYTES || !/^image\/(jpeg|png|webp|gif)$/.test(file.type)) return null;
  return { base64: toBase64(await file.arrayBuffer()), mediaType: file.type };
}
