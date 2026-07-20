import { useEffect, useState } from "react";
import {
  LAST_SERVER_KEY,
  initialServerId,
  loadModelMap,
  preferredModel,
  saveModelForServer,
} from "../lib/modelPrefs.js";

/** Selected server/model + localStorage persistence + correcting an invalid selection.
 *
 * Only **up** servers can be selected: if the selected server goes down we fall back to the first
 * up server, and if the selected model is missing there we pick the remembered one (if any) or the first.
 */
export function useServerModel(servers) {
  const [serverId, setServerId] = useState(initialServerId);
  const [model, setModel] = useState(() => loadModelMap()[String(serverId)] || "");

  const upServers = servers.filter((s) => s.status === "up");
  const selectedServer = upServers.find((s) => s.id === serverId);

  useEffect(() => {
    const up = servers.filter((s) => s.status === "up");
    if (!up.length) return;
    const srv = up.find((s) => s.id === serverId);
    if (!srv) {
      setServerId(up[0].id);
      setModel(preferredModel(up[0]));
      return;
    }
    if (srv.models.length && !srv.models.includes(model)) {
      setModel(preferredModel(srv));
    }
  }, [servers, serverId, model]);

  useEffect(() => {
    localStorage.setItem(LAST_SERVER_KEY, String(serverId));
  }, [serverId]);

  useEffect(() => {
    if (model) saveModelForServer(serverId, model);
  }, [serverId, model]);

  function setTarget(v) {
    setServerId(v.serverId);
    setModel(v.model);
  }

  return { serverId, model, setTarget, upServers, selectedServer };
}
