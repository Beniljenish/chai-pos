/** Owner-only: the shop's records. */
import { useEffect, useState } from "react";
import { Icon, type IconName } from "./icons";
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
// Section ids double as icon names.
const GROUPS: {
  label: string;
  sections: { id: Section & IconName; label: string }[];
}[] =
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

const PHONE = "(max-width: 600px)";

/** True on a phone-sized screen, and kept up to date if the window is resized. */
function usePhone(): boolean {
  const [query] = useState(() =>
    typeof window !== "undefined" && window.matchMedia ? window.matchMedia(PHONE) : null,
  );
  const [phone, setPhone] = useState(() => query?.matches ?? false);
  useEffect(() => {
    if (!query) return;
    const update = () => setPhone(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, [query]);
  return phone;
}

export function ManageScreen() {
  // Phones: Manage opens as a list (like the phone's own Settings) and a
  // section fills the screen with a way back. Tablets: the sidebar and Sales.
  const phone = usePhone();
  const [chosen, setSection] = useState<Section | null>(null);
  const section: Section | null = chosen ?? (phone ? null : "sales");
  if (phone && section !== null) {
    return (
      <main className="manage manage-section">
        <button className="manage-back" aria-label="Back to Manage" onClick={() => setSection(null)}>
          <Icon name="back" size={20} />
          <span>Manage</span>
        </button>
        <div className="manage-body">
          <SectionBody section={section} />
        </div>
      </main>
    );
  }
  return (
    <main className={`manage ${section === null ? "manage-home" : ""}`}>
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
                  <Icon name={s.id} size={20} />
                  <span>{s.label}</span>
                  <span className="subnav-chevron" aria-hidden="true">
                    <Icon name="chevron" size={18} />
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </nav>
      {section !== null && (
        <div className="manage-body">
          <SectionBody section={section} />
        </div>
      )}
    </main>
  );
}

function SectionBody({ section }: { section: Section }) {
  switch (section) {
    case "sales":
      return <SalesScreen />;
    case "reports":
      return <ReportsScreen />;
    case "purchases":
      return <PurchasesScreen />;
    case "stock":
      return <StockScreen />;
    case "dayend":
      return <DayEndScreen />;
    case "recipes":
      return <RecipesScreen />;
    case "shop":
      return <ShopScreen />;
    case "floor":
      return <FloorSetup />;
    case "khata":
      return <KhataScreen />;
    case "staff":
      return <StaffScreen />;
    case "messages":
      return <MessagesScreen />;
    case "tablets":
      return <TabletsScreen />;
  }
}
