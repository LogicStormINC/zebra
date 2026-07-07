import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider, theme } from "antd";
import App from "./App";
import "./styles.css";

const queryClient = new QueryClient();
const openAiFontFamily =
  "'OpenAI Sans', 'Söhne', 'Söhne Mono', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, 'Noto Sans', sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji'";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: "#10a37f",
          colorBgBase: "#161616",
          colorTextBase: "#f3f3f3",
          borderRadius: 14,
          fontFamily: openAiFontFamily,
          wireframe: false,
          lineHeight: 1.5,
          fontSize: 16,
          controlHeight: 42,
        },
        components: {
          Button: {
            controlHeight: 40,
            borderRadius: 12,
            fontWeight: 600,
            fontSize: 15,
            fontFamily: openAiFontFamily,
          },
          Input: {
            controlHeight: 44,
            borderRadius: 12,
            fontSize: 16,
            fontFamily: openAiFontFamily,
          },
          Select: {
            controlHeight: 40,
            borderRadius: 10,
            fontSize: 16,
          },
          Card: {
            headerFontSize: 16,
            bodyPadding: 16,
            colorBgContainer: "rgba(255, 255, 255, 0.045)",
            colorBorderSecondary: "rgba(255, 255, 255, 0.08)",
          },
          Tag: {
            colorTextDescription: "rgba(255, 255, 255, 0.74)",
            fontSize: 13,
            fontFamily: openAiFontFamily,
          },
          Drawer: {
            borderRadiusLG: 16,
          },
          Typography: {
            colorText: "rgba(255, 255, 255, 0.94)",
            colorTextSecondary: "rgba(255, 255, 255, 0.55)",
            titleMarginTop: 0,
            titleMarginBottom: 8,
          },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <App />
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
