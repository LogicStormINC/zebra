import { createElement } from "react";
import {
  ZebraAgentProvider,
  useZebraAction,
  useZebraReadable,
} from "@zebra-agent/react/src/main.ts";

function EventPage(props: { eventId: string }) {
  useZebraReadable("app.ui.route", { route: `/events/${props.eventId}` });
  useZebraAction("app.ui.item.open", (args) => ({
    opened: true,
    itemId: String(args.itemId ?? ""),
  }));
  return createElement("div", null, `Event ${props.eventId}`);
}

export function App() {
  return createElement(
    ZebraAgentProvider,
    {
      config: {
        baseUrl: "/api/zebra",
        clientSessionId: "REPLACED_BY_BFF",
        sessionCredential: "REPLACED_BY_BFF:fence",
      },
      frontendAppId: "app-web",
      profileDigest: "REPLACED_BY_PUBLISHED_PROFILE",
    },
    createElement(EventPage, { eventId: "42" }),
  );
}
