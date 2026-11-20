"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { SalesPoint } from "@/types";
import { formatBDT } from "@/lib/format";

export function SalesChart({ data, locale }: { data: SalesPoint[]; locale: string }) {
  const chartData = data.map((d) => ({
    date: new Intl.DateTimeFormat(locale === "bn" ? "bn-BD" : "en-GB", {
      day: "numeric",
      month: "short",
    }).format(new Date(d.bucket)),
    sales: parseFloat(d.sales),
    invoices: d.invoice_count,
  }));

  return (
    <div className="h-64 w-full" role="img" aria-label="Sales trend chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-primary-200)" vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 12, fill: "var(--color-muted-foreground)" }}
            tickLine={false}
            axisLine={{ stroke: "var(--color-border)" }}
          />
          <YAxis
            tick={{ fontSize: 12, fill: "var(--color-muted-foreground)" }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => `৳${Math.round(v / 100) * 100}`}
            width={72}
          />
          <Tooltip
            formatter={(value) => [formatBDT(typeof value === "number" ? value : 0, locale), "Sales"]}
            contentStyle={{
              borderRadius: "8px",
              border: "1px solid var(--color-border)",
              fontSize: "13px",
            }}
          />
          <Area
            type="monotone"
            dataKey="sales"
            stroke="var(--color-primary)"
            strokeWidth={2}
            fill="var(--color-primary-200)"
            fillOpacity={0.5}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
