import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Stafflytics AI — Vision Operations Center',
  description: 'Enterprise AI Vision & Staff Monitoring System',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        {/* Instant logo preloading hint */}
        <link rel="preload" href="/logo.svg" as="image" type="image/svg+xml" />
        <link
          href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;600;800&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-[#060913] text-slate-100 font-sans antialiased selection:bg-emerald-500 selection:text-black">
        {children}
      </body>
    </html>
  );
}
