// Server status light (not clickable): up → green (reachable, model list arrives),
// down → red (unreachable). Used in the server list in Settings.
import { useT } from "../i18n.js";

export default function StatusLight({ status }) {
  const t = useT();
  const isUp = status === "up";
  return (
    <span
      title={isUp ? t("status.up") : t("status.down")}
      className={`w-3 h-3 rounded-full shrink-0 ${isUp ? "bg-green-500" : "bg-red-500"}`}
    />
  );
}
