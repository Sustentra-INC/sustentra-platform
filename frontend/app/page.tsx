import { S1WorkpaperApp } from "../features/s1/pages/S1WorkpaperApp";

/**
 * The product home: the S1 evidence workpaper. Fixture vs. live data is chosen
 * at runtime by `NEXT_PUBLIC_S1_DATA_MODE` (fixture | backend) inside
 * `S1WorkpaperApp`; see docs/frontend_backend_integration.md.
 */
export default function HomePage() {
  return <S1WorkpaperApp />;
}
