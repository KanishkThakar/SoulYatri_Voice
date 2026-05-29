import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SoulYatri — Voice AI",
  description:
    "Speech-native realtime emotional voice AI. Talk naturally in Hindi, English, or Hinglish.",
  keywords: ["voice AI", "speech", "Hindi", "Hinglish", "conversational AI"],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta name="theme-color" content="#0a0a12" />
      </head>
      <body>{children}</body>
    </html>
  );
}
