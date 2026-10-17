import React from 'react';
import ReactDOM from 'react-dom/client';
import { MantineProvider, createTheme } from '@mantine/core';
import '@mantine/core/styles.css';
import '@fontsource/pixelify-sans/400.css';
import '@fontsource/pixelify-sans/600.css';
import './index.css';
import App from './App';

const theme = createTheme({
  primaryColor: 'teal',
  fontFamily: 'Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
  // Pixel font for headings to match the sprite art; body text stays highly legible.
  headings: { fontFamily: '"Pixelify Sans", system-ui, sans-serif', fontWeight: '600' },
  defaultRadius: 'sm',
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <App />
    </MantineProvider>
  </React.StrictMode>,
);
