/** The pictures that ship with the app (public/dishes). An owner can give a dish one of these with a
 * tap, or paste a link to their own photo. The backend accepts exactly these paths and https links
 * (backend/app/schemas_catalogue.py), so a name added here needs its file added there too. */
export interface DishPicture {
  id: string;
  label: string;
  url: string;
}

export const DISH_PICTURES: DishPicture[] = [
  { id: 'tea', label: 'Tea', url: '/dishes/tea.svg' },
  { id: 'coffee', label: 'Coffee', url: '/dishes/coffee.svg' },
  { id: 'juice', label: 'Juice', url: '/dishes/juice.svg' },
  { id: 'snack', label: 'Snack', url: '/dishes/snack.svg' },
  { id: 'meal', label: 'Meal', url: '/dishes/meal.svg' },
  { id: 'biryani', label: 'Biryani', url: '/dishes/biryani.svg' },
  { id: 'roll', label: 'Roll', url: '/dishes/roll.svg' },
  { id: 'dessert', label: 'Dessert', url: '/dishes/dessert.svg' },
];

/** Whether a photo value is one of the shipped pictures (so the editor can highlight it). */
export const shippedPicture = (url: string): DishPicture | undefined => DISH_PICTURES.find((p) => p.url === url.trim());

/** A photo taken on the owner's phone and kept by the app: `/dish-photos/<32 hex>`. */
const UPLOADED = /^\/dish-photos\/([0-9a-f]{32})$/;
export const uploadedPicture = (url: string): boolean => UPLOADED.test(url.trim());

/** What the editor accepts in the "photo link" box: nothing, a shipped picture, an uploaded photo,
 * or an https link. */
export const photoLinkOk = (url: string): boolean => {
  const v = url.trim();
  return v === '' || v.startsWith('https://') || shippedPicture(v) !== undefined || uploadedPicture(v);
};

/** What to put in an <img src>: an uploaded photo is served by the API, everything else as it is. */
export function photoSrc(url: string, apiUrl: string): string {
  const m = UPLOADED.exec(url.trim());
  return m ? `${apiUrl}/public/dish-photos/${m[1]}` : url.trim();
}
