/**
 * Owner: the cash drawer, shift by shift (in Sales), and the on/off switch
 * (in Shop & GST). Expected = float + cash sales + paid in - paid out.
 */
import { useEffect, useState } from "react";
import { formatRupees } from "../lib/gst";
import type { ShiftReport } from "../lib/types";
import { api } from "./apiClient";
import { explainError } from "./errors";
import { useSession } from "./session";

const time = (iso: string) =>
  new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    timeStyle: "short",
  }).format(new Date(iso));

function Difference({ paise }: { paise: number | null }) {
  if (paise === null)
    return <span className="flag wait">Not ended: cash not counted</span>;
  if (paise === 0) return <span className="flag ok">Matched</span>;
  return (
    <span className={`flag ${paise < 0 ? "bad" : "wait"}`}>
      {formatRupees(Math.abs(paise))} {paise < 0 ? "short" : "over"}
    </span>
  );
}

export function CashDrawer({
  day,
  refreshKey,
}: {
  day: string;
  refreshKey: number;
}) {
  const [report, setReport] = useState<ShiftReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .get<ShiftReport>(`/shifts?business_date=${day}`)
      .then((r) => live && (setReport(r), setError(null)))
      .catch((e) => live && setError(explainError(e)));
    return () => {
      live = false;
    };
  }, [day, refreshKey]);

  if (error) return <p className="error">{error}</p>;
  if (
    !report ||
    (report.shifts.length === 0 && report.cash_outside_shifts.bills === 0)
  )
    return null;

  return (
    <>
      <h2>Cash drawer</h2>
      <p className="muted">
        {report.shifts.length} drawer{report.shifts.length === 1 ? "" : "s"}.
        Tap one for its sums; a drawer that is short or over opens by itself.
      </p>
      <ul className="shift-list">
        {report.shifts.map((s) => {
          // Only a counted drawer that did not match needs the owner's eye now.
          const problem =
            s.difference_paise !== null && s.difference_paise !== 0;
          return (
            <li key={s.id}>
              <details open={problem}>
                <summary className="shift-head">
                  <span className="shift-who">
                    <strong>{s.opened_by_name}</strong>
                    <span className="muted">
                      {s.device} · {time(s.opened_at)}
                      {s.closed_at ? `–${time(s.closed_at)}` : ", still open"}
                    </span>
                  </span>
                  <span className="shift-sum">
                    <span className="num">
                      {formatRupees(s.expected_cash_paise)}
                    </span>
                    <Difference paise={s.difference_paise} />
                  </span>
                </summary>
                {s.closed_by_name && s.closed_by_name !== s.opened_by_name && (
                  <p className="muted">Counted by {s.closed_by_name}</p>
                )}
                <table className="sales-table">
                  <tbody>
                    <tr>
                      <th scope="row">Started with</th>
                      <td className="num">
                        {formatRupees(s.opening_float_paise)}
                      </td>
                    </tr>
                    <tr>
                      <th scope="row">
                        + Cash sales ({s.bills} bill{s.bills === 1 ? "" : "s"}{" "}
                        in all)
                      </th>
                      <td className="num">{formatRupees(s.cash_paise)}</td>
                    </tr>
                    {s.movements.map((m, i) => (
                      <tr key={i}>
                        <th scope="row">
                          {m.kind === "pay_out" ? "− Paid out" : "+ Paid in"}:{" "}
                          {m.reason}{" "}
                          <span className="muted">
                            ({m.by_name}, {time(m.at)})
                          </span>
                        </th>
                        <td className="num">{formatRupees(m.amount_paise)}</td>
                      </tr>
                    ))}
                    <tr className="total-row">
                      <th scope="row">Should be in the drawer</th>
                      <td className="num">
                        {formatRupees(s.expected_cash_paise)}
                      </td>
                    </tr>
                    {s.counted_cash_paise !== null && (
                      <tr className="total-row">
                        <th scope="row">Counted</th>
                        <td className="num">
                          {formatRupees(s.counted_cash_paise)}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
                <p className="muted small-print">
                  Not in the drawer: UPI {formatRupees(s.upi_paise)}
                  {s.card_paise > 0 && `, card ${formatRupees(s.card_paise)}`}.
                  {s.voided_cash_paise > 0 &&
                    ` Voided cash bills: ${formatRupees(s.voided_cash_paise)} (left out above; if that money was not handed back, it is still in the drawer).`}
                  {s.close_note && ` Note: ${s.close_note}`}
                </p>
              </details>
            </li>
          );
        })}
      </ul>
      {report.cash_outside_shifts.bills > 0 && (
        <p className="muted">
          {report.cash_outside_shifts.bills} cash bill
          {report.cash_outside_shifts.bills === 1 ? "" : "s"} (
          {formatRupees(report.cash_outside_shifts.total_paise)}) were not in
          any shift: billed before shifts were switched on, or on an older
          version of the app.
        </p>
      )}
    </>
  );
}

export function CashSettings() {
  const { reloadCatalogue } = useSession();
  const [on, setOn] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ cash_shifts: boolean }>("/shop").then(
      (s) => setOn(s.cash_shifts),
      (e) => setError(explainError(e)),
    );
  }, []);

  async function change(value: boolean) {
    setError(null);
    try {
      const s = await api.patch<{ cash_shifts: boolean }>("/shop", {
        cash_shifts: value,
      });
      setOn(s.cash_shifts);
      void reloadCatalogue();
    } catch (e) {
      setError(explainError(e));
    }
  }

  if (on === null) return error ? <p className="error">{error}</p> : null;
  return (
    <section aria-labelledby="cash-title">
      <h2 id="cash-title">Cash drawer</h2>
      <label className="check email-switch">
        <input
          type="checkbox"
          checked={on}
          onChange={(e) => void change(e.target.checked)}
        />
        <span>
          Count the cash at every shift
          <br />
          <span className="muted">
            Each tablet asks for the cash in the drawer at its first bill and
            for a count at the end, and Sales shows whether it matched. Switch
            off only if the shop takes no cash at the counter.
          </span>
        </span>
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

/** Owner: the most a cashier may take off a bill (README, Phase 6). */
export function DiscountSettings() {
  const { reloadCatalogue } = useSession();
  const [pct, setPct] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ max_discount_bp: number }>("/shop").then(
      (s) => {
        setPct(String(s.max_discount_bp / 100));
        setSaved(String(s.max_discount_bp / 100));
      },
      (e) => setError(explainError(e)),
    );
  }, []);

  async function save() {
    setError(null);
    try {
      const s = await api.patch<{ max_discount_bp: number }>("/shop", {
        max_discount_bp: Math.round(Number(pct) * 100),
      });
      setSaved(String(s.max_discount_bp / 100));
      void reloadCatalogue();
    } catch (e) {
      setError(explainError(e));
    }
  }

  if (pct === null) return error ? <p className="error">{error}</p> : null;
  const valid = /^\d{1,3}(\.\d{1,2})?$/.test(pct) && Number(pct) <= 100;
  return (
    <section aria-labelledby="discount-title">
      <h2 id="discount-title">Discounts</h2>
      <label>
        Most a cashier can take off a bill (%)
        <input
          inputMode="decimal"
          value={pct}
          onChange={(e) => setPct(e.target.value)}
        />
      </label>
      <p className="muted">
        Every discount needs a reason and shows under Sales. You can give any
        discount yourself. A bill over the limit from an older or offline tablet
        is still saved, and flagged for you.
      </p>
      <button disabled={!valid || pct === saved} onClick={() => void save()}>
        Save limit
      </button>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
