import { describe, expect, it } from 'vitest';
import { DISH_PICTURES, photoLinkOk, photoSrc, shippedPicture, uploadedPicture } from './dishPictures';

describe('dish pictures', () => {
  it('are a fixed set with unique ids and paths the backend accepts', () => {
    expect(new Set(DISH_PICTURES.map((p) => p.id)).size).toBe(DISH_PICTURES.length);
    for (const p of DISH_PICTURES) expect(p.url).toMatch(/^\/dishes\/[a-z]{3,20}\.svg$/); // the backend's rule
  });

  it('are recognised, with or without stray spaces', () => {
    expect(shippedPicture('/dishes/tea.svg')?.label).toBe('Tea');
    expect(shippedPicture('  /dishes/juice.svg ')?.id).toBe('juice');
    expect(shippedPicture('https://example.com/tea.jpg')).toBeUndefined();
  });

  it('accept nothing, a shipped picture or an https link, and nothing else', () => {
    for (const ok of ['', '  ', '/dishes/tea.svg', 'https://example.com/a.jpg']) expect(photoLinkOk(ok)).toBe(true);
    for (const bad of ['http://example.com/a.jpg', '/dishes/unknown.svg', '/etc/passwd', 'javascript:alert(1)', 'data:x']) {
      expect(photoLinkOk(bad)).toBe(false);
    }
  });

  it('accept a photo uploaded to the app, and serve it from the API', () => {
    const id = '0123456789abcdef0123456789abcdef';
    expect(uploadedPicture(`/dish-photos/${id}`)).toBe(true);
    expect(photoLinkOk(`/dish-photos/${id}`)).toBe(true);
    expect(photoLinkOk('/dish-photos/short')).toBe(false);
    expect(photoLinkOk(`/dish-photos/${id}/../x`)).toBe(false);
    expect(photoSrc(`/dish-photos/${id}`, 'https://api.example/api/v1')).toBe(`https://api.example/api/v1/public/dish-photos/${id}`);
    expect(photoSrc(' https://x.example/a.jpg ', 'https://api.example')).toBe('https://x.example/a.jpg');
    expect(photoSrc('/dishes/tea.svg', 'https://api.example')).toBe('/dishes/tea.svg');
  });
});
