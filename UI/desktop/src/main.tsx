import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider, App as AntApp, theme } from "antd";
import App from "./App";
import "./styles.css";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#1677ff",
          borderRadius: 14,
          fontSize: 14,
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
