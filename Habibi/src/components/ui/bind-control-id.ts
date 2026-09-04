/**
 * Pair a visible Field label with the control sitting next to it.
 *
 * Six business forms cloned a `<Field label>` helper that rendered the words
 * and never connected them: three used `<Label>` with no `htmlFor`, three used
 * a `<div>`. The screen looked labelled; the accessibility tree said
 * "edit, blank". This is the small adopted helper — the `useConfirm` shape —
 * rather than the deleted shadcn form stack.
 *
 * `id` goes on the labelable node, not whichever React element is first:
 * Radix `Select` is a context provider with no DOM, so the id has to land on
 * `SelectTrigger`. A Radix `Slider` root is not labelable either, so it
 * also receives `aria-label`.
 *
 * Kept free of the DOM so the pairing can be tested under vitest's
 * `environment: "node"`.
 */
import { Children, cloneElement, isValidElement, type ReactElement, type ReactNode } from "react";

import { SelectTrigger } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";

export function bindControlId(children: ReactNode, id: string, label?: string): ReactNode {
  let bound = false;
  return Children.map(children, (child) => {
    if (bound || !isValidElement(child)) return child;
    bound = true;
    return bindElementId(child, id, label);
  });
}

function bindElementId(element: ReactElement, id: string, label?: string): ReactElement {
  if (element.type === Slider) {
    return cloneElement(element as ReactElement<{ id?: string; "aria-label"?: string }>, {
      id,
      ...(label ? { "aria-label": label } : {}),
    });
  }

  let foundTrigger = false;
  const nextNested = Children.map((element.props as { children?: ReactNode }).children, (node) => {
    if (foundTrigger || !isValidElement<{ id?: string }>(node) || node.type !== SelectTrigger) {
      return node;
    }
    foundTrigger = true;
    return cloneElement(node, { id });
  });
  if (foundTrigger) {
    return cloneElement(element, undefined, ...Children.toArray(nextNested));
  }
  return cloneElement(element as ReactElement<{ id?: string }>, { id });
}
