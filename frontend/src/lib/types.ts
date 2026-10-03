/** Shapes shared with the backend API (see backend/app/schemas_*.py). */
import type { GstType } from './gst';

export interface RecipeLine {
  ingredient_id: string;
  ingredient_name: string;
  base_unit: string;
  qty: string;
}

export interface MenuItem {
  id: string;
  name: string;
  category: string;
  price_paise: number;
  gst_rate_bp: number;
  tax_inclusive: boolean;
  hsn_sac: string;
  is_active: boolean;
  recipe: { id: string; version: number; lines: RecipeLine[] } | null;
  modifier_ids: string[];
}

export interface Modifier {
  id: string;
  name: string;
  price_delta_paise: number;
  scale_factor: string;
  is_active: boolean;
  lines: { ingredient_id: string; qty_delta: string }[];
}

export interface Catalogue {
  shop: { name: string; gst_type: GstType; gstin: string | null; state_code: string; address: string };
  menu_items: MenuItem[];
  modifiers: Modifier[];
}

export interface User {
  id: string;
  name: string;
  phone: string;
  role: 'owner' | 'cashier';
}

export interface Device {
  id: string;
  name: string;
  code: string;
  is_active: boolean;
}

export interface SyncBillLine {
  menu_item_id: string;
  recipe_id: string | null;
  name: string;
  unit_price_paise: number;
  qty: number;
  gst_rate_bp: number;
  tax_inclusive: boolean;
  modifiers: {
    modifier_id: string;
    name: string;
    price_delta_paise: number;
    scale_factor: string;
    lines: { ingredient_id: string; qty_delta: string }[];
  }[];
  totals: { gross: number; taxable: number; cgst: number; sgst: number; total: number };
}

export interface SyncBill {
  id: string;
  local_seq: number;
  invoice_no: string;
  sold_at: string;
  payment_mode: 'cash' | 'upi' | 'card';
  gst_type: GstType;
  lines: SyncBillLine[];
  totals: {
    taxable: number;
    cgst: number;
    sgst: number;
    subtotal: number;
    round_off: number;
    total: number;
  };
}

export interface SyncResult {
  id: string;
  status: 'accepted' | 'duplicate' | 'rejected';
  invoice_no: string | null;
  totals_mismatch: boolean;
  reason: string | null;
}

// ---- owner: stock ----
import type { BaseUnit } from './qty';
export type { BaseUnit };

export interface Ingredient {
  id: string;
  name: string;
  kind: 'raw' | 'prep';
  base_unit: BaseUnit;
  scales_with_size: boolean;
  is_active: boolean;
  reorder_level: string | null;
  pack_units: { id: string; name: string; qty_in_base: string }[];
}

export interface StockRow {
  ingredient_id: string;
  name: string;
  kind: 'raw' | 'prep';
  base_unit: BaseUnit;
  on_hand: string;
  is_negative: boolean;
  below_reorder: boolean;
  has_opening: boolean;
  is_active: boolean;
}

export interface LedgerRow {
  id: string;
  qty_delta: string;
  reason: 'opening' | 'stock_in' | 'sale' | 'prep_in' | 'prep_out' | 'void' | 'wastage' | 'count_adjustment';
  business_date: string;
  created_at: string;
}

export interface Recipe {
  id: string;
  version: number;
  effective_from: string;
  yield_qty: string | null;
  yield_inputs: { ingredient_id: string; ml_per_kg: string; portion_ml: string; grams_per_portion: string } | null;
  created_by_name?: string | null;
  lines: RecipeLine[];
}


// ---- day end ----
export type WastageReason = 'spoiled' | 'spilled' | 'remake' | 'prep_loss' | 'staff' | 'complimentary' | 'theft';
export type DayStatus = 'counting' | 'submitted' | 'approved';

export interface WastageRow {
  id: string;
  name: string;
  is_menu_item: boolean;
  qty: string;
  base_unit: BaseUnit | null;
  reason: WastageReason;
  note: string;
  value_paise: number | null;
  created_by_name: string;
  created_at: string;
}

export interface SheetItem {
  ingredient_id: string;
  name: string;
  kind: 'raw' | 'prep';
  base_unit: BaseUnit;
  count_frequency: string;
  pack_units: { id: string; name: string; qty_in_base: string }[];
  counted: boolean;
  recount: boolean;
}

export interface CountSheet {
  business_date: string;
  status: DayStatus;
  items: SheetItem[];
}

export interface ReportLine {
  ingredient_id: string;
  name: string;
  base_unit: BaseUnit;
  opening: string;
  stock_in: string;
  prep_in: string;
  prep_out: string;
  sold: string;
  wasted: string;
  other: string;
  expected: string;
  counted: string;
  variance: string;
  variance_paise: number;
  cost_per_unit_paise: string;
  expected_usage: string;
  actual_usage: string;
  adherence_pct: string | null;
  tolerance_bp: number;
  flagged: boolean;
  recounted: boolean;
  has_opening: boolean;
}

export interface DayReport {
  business_date: string;
  status: DayStatus;
  submitted_by_name: string | null;
  approved_by_name: string | null;
  lines: ReportLine[];
  missing_paise: number;
  surplus_paise: number;
  flagged_count: number;
  wastage_paise: number;
  wastage_by_reason: Record<string, number>;
  late_bills: number;
  late_bills_explained_paise: number;
}
