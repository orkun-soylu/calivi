import { IMAGE_SIZES, IMAGE_STEPS } from "../../lib/imageOptions.js";
import { useT } from "../../i18n.js";

/** Size / steps / seed for an image-generation model, above the text box. Empty = server default. */
export default function ImageOptions({ value, onChange }) {
  const t = useT();
  const cls = "bg-neutral-800 text-xs rounded-lg px-2 py-1 border border-neutral-700 min-w-0";
  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="flex flex-wrap items-center gap-2 mb-2 text-xs text-neutral-400">
      <span aria-hidden="true">🎨</span>
      <label className="flex items-center gap-1">
        {t("image.size")}
        <select value={value.size} onChange={set("size")} className={cls}>
          <option value="">{t("image.default")}</option>
          {IMAGE_SIZES.map(([v, key]) => (
            <option key={v} value={v}>
              {t(key)} · {v.replace("x", "×")}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1">
        {t("image.steps")}
        <select value={value.steps} onChange={set("steps")} className={cls}>
          <option value="">{t("image.default")}</option>
          {IMAGE_STEPS.map((n) => (
            <option key={n} value={String(n)}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1">
        {t("image.seed")}
        <input
          value={value.seed}
          onChange={(e) => onChange({ ...value, seed: e.target.value.replace(/\D/g, "") })}
          inputMode="numeric"
          placeholder={t("image.random")}
          className={`${cls} w-28`}
        />
      </label>
    </div>
  );
}
