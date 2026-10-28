import type { ReactNode } from "react";
import ProtectedRoute from "@/components/auth/ProtectedRoute";

export default function AccountLayout({ children }: { children: ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>;
}
