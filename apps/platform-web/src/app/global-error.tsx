'use client';

import { useEffect } from 'react';

// global-error replaces the root layout when it errors, so globals.css is not
// loaded here — styles must be inline and self-contained.
export default function GlobalError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[zebra-console]', error);
  }, [error]);

  return (
    <html lang='zh-CN'>
      <body
        style={{
          margin: 0,
          display: 'flex',
          minHeight: '100vh',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'system-ui, sans-serif'
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <h1 style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>页面发生错误</h1>
          <p style={{ opacity: 0.7, marginBottom: '1rem' }}>
            {error.digest ? `错误摘要：${error.digest}` : '请稍后重试或联系平台管理员。'}
          </p>
          <button
            onClick={reset}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '0.5rem',
              border: '1px solid #888',
              background: 'transparent',
              cursor: 'pointer'
            }}
          >
            重试
          </button>
        </div>
      </body>
    </html>
  );
}
