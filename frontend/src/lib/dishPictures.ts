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

/** What the editor accepts in the "photo link" box: nothing, a shipped picture, or an https link. */
export const photoLinkOk = (url: string): boolean => {
  const v = url.trim();
  return v === '' || v.startsWith('https://') || shippedPicture(v) !== undefined;
};
