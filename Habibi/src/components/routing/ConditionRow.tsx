import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FIELDS, OPERATORS_BY_TYPE, type Condition, type RuleOperator } from "@/data/routing-seed";

type Props = {
  cond: Condition;
  onChange: (c: Condition) => void;
  onRemove: () => void;
};

export function ConditionRow({ cond, onChange, onRemove }: Props) {
  const field = FIELDS.find((f) => f.key === cond.field) ?? FIELDS[0];
  const ops = OPERATORS_BY_TYPE[field.type];

  const setField = (key: string) => {
    const nf = FIELDS.find((f) => f.key === key)!;
    const nextOp = OPERATORS_BY_TYPE[nf.type][0];
    let val: Condition["value"] = "";
    if (nf.type === "enum") val = nf.options?.[0] ?? "";
    else if (nf.type === "number") val = 0;
    else if (nf.type === "boolean") val = true;
    onChange({ ...cond, field: key, op: nextOp, value: val });
  };

  return (
    <div className="flex items-center gap-075">
      <Select value={cond.field} onValueChange={setField}>
        <SelectTrigger className="h-400 w-[9.375rem] text-body-small">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {FIELDS.map((f) => (
            <SelectItem key={f.key} value={f.key}>
              {f.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={cond.op} onValueChange={(v) => onChange({ ...cond, op: v as RuleOperator })}>
        <SelectTrigger className="h-400 w-1000 text-body-small">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {ops.map((o) => (
            <SelectItem key={o} value={o}>
              {o}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {field.type === "enum" ? (
        <Select value={String(cond.value)} onValueChange={(v) => onChange({ ...cond, value: v })}>
          <SelectTrigger className="h-400 flex-1 text-body-small">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.options!.map((o) => (
              <SelectItem key={o} value={o}>
                {o}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : field.type === "boolean" ? (
        <Select
          value={String(cond.value)}
          onValueChange={(v) => onChange({ ...cond, value: v === "true" })}
        >
          <SelectTrigger className="h-400 flex-1 text-body-small">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="true">true</SelectItem>
            <SelectItem value="false">false</SelectItem>
          </SelectContent>
        </Select>
      ) : (
        <Input
          className="h-400 flex-1 text-body-small"
          type={field.type === "number" ? "number" : "text"}
          value={String(cond.value)}
          onChange={(e) =>
            onChange({
              ...cond,
              value: field.type === "number" ? Number(e.target.value) : e.target.value,
            })
          }
        />
      )}

      <Button variant="ghost" size="icon" className="h-400 w-400 shrink-0" onClick={onRemove}>
        <X className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
