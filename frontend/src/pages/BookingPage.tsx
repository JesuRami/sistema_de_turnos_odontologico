import BookingFlow from "../features/booking/BookingFlow";

/** Ruta pública `/b/:slug` (C-07): solo compone; el flujo vive en `features/booking`. */
function BookingPage(): JSX.Element {
  return <BookingFlow />;
}

export default BookingPage;
