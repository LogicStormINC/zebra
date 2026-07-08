import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider, theme } from "antd";
import App from "./App";
import "./styles.css";

const queryClient = new QueryClient();
const workbenchFontFamily =
  "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: "#f59e0b",
          colorBgBase: "#0f0f10",
          colorBgContainer: "#171717",
          colorTextBase: "#f4f4f5",
          colorTextSecondary: "#a1a1aa",
          colorBorder: "rgba(255, 255, 255, 0.08)",
          borderRadius: 10,
          fontFamily: workbenchFontFamily,
          wireframe: false,
          lineHeight: 1.57,
          fontSize: 14,
          controlHeight: 36,
        },
        components: {
          Button: {
            controlHeight: 36,
            borderRadius: 10,
            fontWeight: 500,
            fontSize: 14,
            fontFamily: workbenchFontFamily,
          },
          Input: {
            controlHeight: 40,
            borderRadius: 10,
            fontSize: 16,
            fontFamily: workbenchFontFamily,
          },
          Select: {
            controlHeight: 36,
            borderRadius: 10,
            fontSize: 14,
          },
          Card: {
            headerFontSize: 15,
            bodyPadding: 16,
            colorBgContainer: "#171717",
            colorBorderSecondary: "rgba(255, 255, 255, 0.08)",
          },
          Tag: {
            colorTextDescription: "#a1a1aa",
            fontSize: 12,
            fontFamily: workbenchFontFamily,
          },
          Drawer: {
            borderRadiusLG: 10,
          },
          Typography: {
            colorText: "#f4f4f5",
            colorTextSecondary: "#a1a1aa",
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
