import clsx from "clsx";

interface LabeledInputProps {
  icon: React.ReactNode;
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoComplete?: string;
  required?: boolean;
}

export default function LabeledInput({
  icon,
  label,
  type,
  value,
  onChange,
  placeholder,
  autoComplete,
  required,
}: LabeledInputProps) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[12px] font-medium text-muted">{label}</span>
      <div
        className={clsx(
          "flex items-center gap-2",
          "rounded-lg border border-white/12 bg-background",
          "px-3 py-2 focus-within:border-primary",
        )}
      >
        <span className="text-muted">{icon}</span>
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          required={required}
          placeholder={placeholder}
          className="w-full bg-transparent text-[14px] text-normal outline-none"
        />
      </div>
    </label>
  );
}
