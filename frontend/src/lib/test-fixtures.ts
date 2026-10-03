import type { Catalogue } from './types';

/** A one-item menu for unit tests. */
export const testCatalogue: Catalogue = {
  shop: { name: 'Test', gst_type: 'regular', gstin: null, state_code: '33', address: '' },
  menu_items: [
    {
      id: 'tea', name: 'Masala tea', category: 'Tea', price_paise: 2000, gst_rate_bp: 500,
      tax_inclusive: true, hsn_sac: '996331', is_active: true,
      recipe: { id: 'r-tea', version: 1, lines: [] }, modifier_ids: ['large'],
    },
  ],
  modifiers: [
    { id: 'large', name: 'Large', price_delta_paise: 1000, scale_factor: '1.500', is_active: true, lines: [] },
  ],
};
