// Field for a 6-digit TOTP code: digits only, and the browser may fill it
// from an SMS or a password manager (autocomplete "one-time-code").
import { TextInput } from "@mantine/core";

export const CODE_PATTERN = /^[0-9]{6}$/;

type CodeInputProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
};

export function CodeInput({ label, value, onChange }: CodeInputProps) {
  return (
    <TextInput
      label={label}
      value={value}
      onChange={(event) => onChange(event.currentTarget.value.replace(/\D/g, "").slice(0, 6))}
      inputMode="numeric"
      autoComplete="one-time-code"
      maxLength={6}
      required
      data-autofocus
    />
  );
}
