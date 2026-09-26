"use client";

import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { cva, type VariantProps } from "class-variance-authority";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";

const Select = SelectPrimitive.Root;

const SelectGroup = SelectPrimitive.Group;

const SelectValue = SelectPrimitive.Value;

/*
 * Two sizes, named — the same `default`/`compact` vocabulary Button already uses.
 *
 * They were not named before, so every dense surface re-declared the dense look
 * by hand: 57 triggers carried 18 different className strings and the raw
 * `<select>`s beside them carried 29 more. `h-400` here is what 34 of those
 * strings were reaching for; `h-7`, `h-300` and `h-200` were each one file's
 * guess at the same thing.
 *
 * `compact` is for dense surfaces only — filter bars, toolbars, table rows —
 * never a form's default, which is the same rule Button states at its own
 * `compact`.
 */
const selectTriggerVariants = cva(
  "focus-ring flex w-full items-center justify-between whitespace-nowrap rounded-medium border border-border-input bg-background-input px-075 cursor-pointer data-[placeholder]:text-text-subtlest hover:bg-background-input-hovered disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1",
  {
    variants: {
      size: {
        default: "h-9 py-075 text-body",
        compact: "h-400 text-body-small",
      },
    },
    defaultVariants: { size: "default" },
  },
);

export interface SelectTriggerProps
  extends
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>,
    VariantProps<typeof selectTriggerVariants> {
  /** Leading glyph inside the trigger. Dashboard's filter pills need one. */
  icon?: React.ReactNode;
}

const SelectTrigger = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Trigger>,
  SelectTriggerProps
>(({ className, children, size, icon, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      selectTriggerVariants({ size }),
      // The icon sits before the value, so the free space has to move to the
      // chevron's left instead of being split three ways by `justify-between`.
      icon && "gap-075 [&>*:nth-child(2)]:mr-auto",
      className,
    )}
    {...props}
  >
    {icon ? (
      <span aria-hidden className="shrink-0 text-text-subtle [&>svg]:size-3.5">
        {icon}
      </span>
    ) : null}
    {children}
    <SelectPrimitive.Icon asChild>
      <ChevronDown className="h-4 w-4 opacity-50" />
    </SelectPrimitive.Icon>
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

const SelectScrollUpButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollUpButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpButton
    ref={ref}
    className={cn("flex cursor-default items-center justify-center py-050", className)}
    {...props}
  >
    <ChevronUp className="h-4 w-4" />
  </SelectPrimitive.ScrollUpButton>
));
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName;

const SelectScrollDownButton = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.ScrollDownButton>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownButton
    ref={ref}
    className={cn("flex cursor-default items-center justify-center py-050", className)}
    {...props}
  >
    <ChevronDown className="h-4 w-4" />
  </SelectPrimitive.ScrollDownButton>
));
SelectScrollDownButton.displayName = SelectPrimitive.ScrollDownButton.displayName;

const SelectContent = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
  <SelectPrimitive.Portal>
    <SelectPrimitive.Content
      ref={ref}
      className={cn(
        "relative z-50 max-h-(--radix-select-content-available-height) min-w-[8rem] overflow-y-auto overflow-x-hidden rounded-large border border-border bg-surface-overlay text-text shadow-overlay data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 origin-(--radix-select-content-transform-origin)",
        position === "popper" &&
          "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
        className,
      )}
      position={position}
      {...props}
    >
      <SelectScrollUpButton />
      <SelectPrimitive.Viewport
        className={cn(
          "p-050",
          position === "popper" &&
            "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]",
        )}
      >
        {children}
      </SelectPrimitive.Viewport>
      <SelectScrollDownButton />
    </SelectPrimitive.Content>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = SelectPrimitive.Content.displayName;

const SelectLabel = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Label>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Label
    ref={ref}
    className={cn("px-100 py-075 text-body-small font-medium text-text-subtle", className)}
    {...props}
  />
));
SelectLabel.displayName = SelectPrimitive.Label.displayName;

const SelectItem = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Item
    ref={ref}
    className={cn(
      "relative flex w-full cursor-default select-none items-center rounded-small py-075 pl-100 pr-400 text-body outline-none focus:bg-background-selected focus:text-text-selected data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className,
    )}
    {...props}
  >
    <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-4 w-4" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;

const SelectSeparator = React.forwardRef<
  React.ElementRef<typeof SelectPrimitive.Separator>,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("-mx-050 my-050 h-px bg-border", className)}
    {...props}
  />
));
SelectSeparator.displayName = SelectPrimitive.Separator.displayName;

/**
 * A value picker over a flat list of options — the shape 80-odd call sites want.
 *
 * Those sites were raw `<select>`s, because this file only ever exported the
 * primitives and the five-element incantation is too much ceremony to repeat per
 * filter. Repeating it 80 times would also repeat the two things Radix does not
 * do for you, and get them wrong in different places:
 *
 *   - an item's value may not be the empty string, so "none" needs a sentinel
 *   - `value=""` on the root means *unset*, which is how a placeholder shows
 *
 * Both live here, once. Sites that need grouped or custom-rendered items still
 * use the primitives directly — `VoiceCatalogBrowser` and `ConditionRow` do.
 */
export type SelectOption = {
  value: string;
  label: React.ReactNode;
  disabled?: boolean;
};

/**
 * Stands in for `""` when "nothing" is a choice the user can pick *back*, not
 * merely the state before they chose. Radix rejects an empty item value outright
 * (it cannot tell it from "no selection"), so the swap happens at this boundary
 * and no caller ever sees it.
 */
export const SELECT_NONE = "__none__";

export interface SelectFieldProps extends VariantProps<typeof selectTriggerVariants> {
  value: string | null | undefined;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  /** Shown when `value` is empty. Not selectable — use an option for that. */
  placeholder?: string;
  disabled?: boolean;
  /** Layout only: width, flex, margins. Chrome comes from `size`. */
  className?: string;
  /** Width of the popover; defaults to the trigger's. */
  contentClassName?: string;
  icon?: React.ReactNode;
  id?: string;
  "aria-label"?: string;
  name?: string;
}

export function SelectField({
  value,
  onChange,
  options,
  placeholder,
  disabled,
  className,
  contentClassName,
  size,
  icon,
  id,
  name,
  "aria-label": ariaLabel,
}: SelectFieldProps) {
  // An empty `value` means one of two different things, and they render
  // differently: the placeholder if nothing has been chosen, or the "none"
  // option's own label if the list offers "none" as a choice.
  const offersNone = options.some((o) => !o.value);
  return (
    <Select
      // `""` is Radix's controlled "nothing selected": it renders the
      // placeholder. `undefined` would do the same but makes the Select
      // uncontrolled, and a picker whose options arrive after mount then warns
      // "changing from uncontrolled to controlled" the moment it gets a value.
      value={value ? value : offersNone ? SELECT_NONE : ""}
      onValueChange={(v) => onChange(v === SELECT_NONE ? "" : v)}
      disabled={disabled}
      name={name}
    >
      <SelectTrigger id={id} aria-label={ariaLabel} className={className} size={size} icon={icon}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent className={contentClassName}>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value || SELECT_NONE} disabled={o.disabled}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
  SelectScrollUpButton,
  SelectScrollDownButton,
};
