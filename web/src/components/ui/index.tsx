/**
 * [INPUT]: Base UI 与 Lucide；语义主题变量。
 * [OUTPUT]: 本地可控的 Button / Input / Dialog / Tabs / Select / Checkbox / Switch / Accordion。
 * [POS]: 唯一交互原语层；不依赖 Radix。
 * [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
 */
import {
  useEffect,
  useId,
  useRef,
  type ComponentProps,
  type ReactNode,
} from "react";
import { Button as BaseButton } from "@base-ui/react/button";
import { Input as BaseInput } from "@base-ui/react/input";
import { Dialog } from "@base-ui/react/dialog";
import { Select } from "@base-ui/react/select";
import { Checkbox } from "@base-ui/react/checkbox";
import { Switch } from "@base-ui/react/switch";
import { Tabs } from "@base-ui/react/tabs";
import { Accordion } from "@base-ui/react/accordion";
import { Check, ChevronDown, X } from "lucide-react";
export function Button({
  className = "",
  variant = "outline",
  ...props
}: ComponentProps<typeof BaseButton> & {
  variant?: "primary" | "outline" | "ghost" | "danger";
}) {
  const id = useId().replace(/:/g, "");
  return (
    <BaseButton
      data-od-id={`button-${id}`}
      {...props}
      className={`button button-${variant} ${className}`}
    />
  );
}
export function Input({
  className = "",
  ...props
}: ComponentProps<typeof BaseInput>) {
  const id = useId().replace(/:/g, "");
  return (
    <BaseInput
      data-od-id={`input-${id}`}
      {...props}
      className={`input ${className}`}
    />
  );
}
export function Modal({
  open,
  close,
  title,
  description,
  children,
  wide = false,
  returnFocus,
}: {
  open: boolean;
  close: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
  returnFocus?: HTMLElement | null;
}) {
  const fallback = useRef<HTMLElement | null>(null);
  if (open && !fallback.current)
    fallback.current = document.activeElement as HTMLElement;
  useEffect(() => {
    if (!open) fallback.current = null;
  }, [open]);
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(v) => {
        if (!v) close();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="dialog-backdrop" />
        <Dialog.Popup
          className={`dialog ${wide ? "dialog-wide" : ""}`}
          finalFocus={() =>
            returnFocus?.isConnected && returnFocus.getClientRects().length
              ? returnFocus
              : fallback.current?.isConnected &&
                  fallback.current.getClientRects().length
                ? fallback.current
                : document.querySelector<HTMLElement>('[data-od-focus-fallback]')
          }
          data-od-id="dialog"
        >
          <div className="dialog-heading">
            <div>
              <Dialog.Title className="dialog-title">{title}</Dialog.Title>
              {description && (
                <Dialog.Description className="muted">
                  {description}
                </Dialog.Description>
              )}
            </div>
            <Dialog.Close
              className="button button-ghost icon-button"
              aria-label="关闭弹层"
            >
              <X />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function Segments({
  value,
  onChange,
  items,
  label,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  items: { value: string; label: ReactNode }[];
  label: string;
  className?: string;
}) {
  const id = useId().replace(/:/g, "");
  return (
    <Tabs.Root
      value={value}
      onValueChange={(v) => onChange(String(v))}
      className={className}
    >
      <Tabs.List className="segments" aria-label={label}>
        {items.map((i, index) => (
          <Tabs.Tab
            value={i.value}
            key={i.value}
            className="segment"
            data-od-id={`tab-${id}-${index}`}
          >
            {i.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
    </Tabs.Root>
  );
}
export function SelectField({
  value,
  onChange,
  options,
  label,
  className = "",
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  label: string;
  className?: string;
}) {
  const odId = useId().replace(/:/g, "");
  return (
    <Select.Root
      value={value}
      onValueChange={(v) => v != null && onChange(v)}
      items={options.map((v) => ({ label: v, value: v }))}
    >
      <Select.Trigger
        data-od-id={`select-${odId}`}
        className={`select-trigger ${className}`}
        aria-label={label}
      >
        <Select.Value />
        <Select.Icon>
          <ChevronDown size={14} />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Positioner
          sideOffset={5}
          className="select-positioner"
          alignItemWithTrigger={false}
        >
          <Select.Popup className="select-popup">
            <Select.List>
              {options.map((v) => (
                <Select.Item key={v} value={v} className="select-item">
                  <Select.ItemText>{v}</Select.ItemText>
                  <Select.ItemIndicator>
                    <Check size={15} />
                  </Select.ItemIndicator>
                </Select.Item>
              ))}
            </Select.List>
          </Select.Popup>
        </Select.Positioner>
      </Select.Portal>
    </Select.Root>
  );
}
export function CheckField({
  checked,
  onChange,
  children,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={`check-row ${disabled ? "disabled" : ""}`}>
      <Checkbox.Root
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        className="checkbox"
      >
        <Checkbox.Indicator>
          <Check size={13} />
        </Checkbox.Indicator>
      </Checkbox.Root>
      <span>{children}</span>
    </label>
  );
}
export function SwitchField({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  const odId = useId().replace(/:/g, "");
  return (
    <Switch.Root
      data-od-id={`switch-${odId}`}
      checked={checked}
      onCheckedChange={onChange}
      className="switch"
      aria-label={label}
    >
      <Switch.Thumb className="switch-thumb" />
    </Switch.Root>
  );
}
export function Tree({
  branches,
}: {
  branches: { title: string; children: string[] }[];
}) {
  return (
    <Accordion.Root
      multiple
      defaultValue={branches.map((_, i) => String(i))}
      className="outline-tree"
    >
      {branches.map((b, i) => (
        <Accordion.Item key={b.title} value={String(i)} className="tree-item">
          <Accordion.Header>
            <Accordion.Trigger className="tree-trigger">
              <ChevronDown size={16} />
              <span>{b.title}</span>
              <span className="muted tree-count">{b.children.length}</span>
            </Accordion.Trigger>
          </Accordion.Header>
          <Accordion.Panel className="tree-panel">
            <ul>
              {b.children.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion.Root>
  );
}
