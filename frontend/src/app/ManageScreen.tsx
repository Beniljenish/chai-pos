/** Owner-only: the shop's records. */
import { useState } from "react";
import { DayEndScreen } from "./DayEndScreen";
import { FloorSetup } from "./FloorSetup";
import { KhataScreen } from "./CustomersUI";
import { MessagesScreen } from "./MessagesScreen";
import { PurchasesScreen } from "./PurchasesScreen";
import { ReportsScreen } from "./ReportsScreen";
import { RecipesScreen } from "./RecipesScreen";
import { SalesScreen } from "./SalesScreen";
import { ShopScreen } from "./ShopScreen";
import { StaffScreen } from "./StaffScreen";
import { TabletsScreen } from "./TabletsScreen";
import { StockScreen } from "./StockScreen";

type Section =
  | "sales"
  | "stock"
  | "dayend"
  | "recipes"
  | "shop"
  | "staff"
  | "tablets"
  | "floor"
  | "reports"
  | "purchases"
  | "khata"
  | "messages";
// Grouped by what the owner is doing: checking money, looking after stock, or
// setting the shop up. Twelve sections in one sideways-scrolling row hid most
// of them on a phone.
const GROUPS: { label: string; sections: { id: Section; label: string }[] }[] =
  [
    {
      label: "Money",
      sections: [
        { id: "sales", label: "Sales" },
        { id: "reports", label: "Reports" },
        { id: "khata", label: "Khata" },
      ],
    },
    {
      label: "Stock",
      sections: [
        { id: "stock", label: "Stock" },
        { id: "purchases", label: "Purchases" },
        { id: "dayend", label: "Day end" },
        { id: "recipes", label: "Recipes" },
      ],
    },
    {
      label: "Setup",
      sections: [
        { id: "shop", label: "Shop & GST" },
        { id: "staff", label: "Staff" },
        { id: "floor", label: "Floor" },
        { id: "tablets", label: "Tablets" },
        { id: "messages", label: "Messages" },
      ],
    },
  ];

export function ManageScreen() {
  const [section, setSection] = useState<Section>("sales");
  return (
    <main className="manage">
      <nav className="subnav" aria-label="Manage">
        {GROUPS.map((g) => (
          <div
            key={g.label}
            className="subnav-group"
            role="group"
            aria-label={g.label}
          >
            <span className="subnav-label" aria-hidden="true">
              {g.label}
            </span>
            <div className="subnav-items">
              {g.sections.map((s) => (
                <button
                  key={s.id}
                  aria-pressed={section === s.id}
                  onClick={() => setSection(s.id)}
                >
                  {s.label}
                </button>
              ))}
            </div>
          </div>
        ))}
      </nav>
      <div className="manage-body">
        {section === "sales" ? (
          <SalesScreen />
        ) : section === "reports" ? (
          <ReportsScreen />
        ) : section === "purchases" ? (
          <PurchasesScreen />
        ) : section === "stock" ? (
          <StockScreen />
        ) : section === "dayend" ? (
          <DayEndScreen />
        ) : section === "recipes" ? (
          <RecipesScreen />
        ) : section === "shop" ? (
          <ShopScreen />
        ) : section === "floor" ? (
          <FloorSetup />
        ) : section === "khata" ? (
          <KhataScreen />
        ) : section === "staff" ? (
          <StaffScreen />
        ) : section === "messages" ? (
          <MessagesScreen />
        ) : (
          <TabletsScreen />
        )}
      </div>
    </main>
  );
}
