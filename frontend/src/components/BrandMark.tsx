import { Check } from "@phosphor-icons/react";

export function BrandMark() {
  return (
    <span className="brand-lockup" aria-label="JobPicky">
      <span className="brand-mark" aria-hidden="true">
        <Check size={20} weight="bold" />
      </span>
      <span className="brand-name">
        Job<span>Picky</span>
      </span>
    </span>
  );
}
