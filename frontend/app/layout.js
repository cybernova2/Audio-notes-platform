import Link from "next/link";
import "./globals.css";

export const metadata = {
  title: "Audio Notes",
  description: "Upload audio, get a transcript and a summary.",
};

// Wraps every page: the header with navigation, then the page itself.
export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <header className="header">
          <Link href="/" className="brand">
            Audio Notes
          </Link>
          <nav>
            <Link href="/">Uploads</Link>
            <Link href="/architecture">Architecture</Link>
          </nav>
        </header>
        <main className="main">{children}</main>
      </body>
    </html>
  );
}
