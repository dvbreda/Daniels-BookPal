/**
 * Stub in plaats van foliate's pdf.js.
 *
 * De echte versie importeert een meegeleverde pdf.js-distributie van ~13 MB.
 * BookPal heeft die niet nodig: pdf-pagina's worden server-side gerenderd
 * (`/api/books/{id}/pages/{n}`, zie bookpal/images) en gelezen met dezelfde
 * stripleer als cbz en cbr. Zonder deze stub zou `view.js` bij het bouwen
 * struikelen over een import die we bewust hebben weggelaten.
 *
 * Wordt alleen bereikt als iemand een pdf aan foliate voert; dat pad bestaat
 * in BookPal niet.
 */

export const makePDF = () => {
    throw new Error("BookPal rendert pdf's server-side; foliate's pdf.js wordt niet gebruikt")
}
