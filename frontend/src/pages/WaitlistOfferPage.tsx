import OfferPage from "../features/waitlist-offer/OfferPage";

/** Ruta pública `/o/:token` (C-12): solo compone; el flujo vive en `features/waitlist-offer`. */
function WaitlistOfferPage(): JSX.Element {
  return <OfferPage />;
}

export default WaitlistOfferPage;
