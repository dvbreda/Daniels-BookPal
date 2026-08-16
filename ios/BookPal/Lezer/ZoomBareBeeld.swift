import SwiftUI
import UIKit

/// Een pagina waar je op in kunt zoomen.
///
/// Dit is een `UIScrollView` en geen SwiftUI-gebaar, omdat een scrollview het
/// hele gedrag al goed heeft: knijpen om te zoomen, slepen binnen een
/// ingezoomde pagina, terugveren aan de rand, en dubbeltikken. Dat namaken met
/// `scaleEffect` en een `MagnifyGesture` levert altijd iets dat net niet
/// meebeweegt met je vingers.
///
/// Belangrijk voor het bladeren: op schaal 1 is er niets om te scrollen, dus
/// laat de scrollview de veeg door aan de pager eronder. Pas als je ingezoomd
/// bent pakt hij het slepen zelf. Dat is precies het gedrag dat je wilt en het
/// is de reden dat de zoom hier per pagina zit en niet over het hele boek.
struct ZoomBareBeeld: UIViewRepresentable {
    let beeld: UIImage
    /// Hoe de pagina in beeld gezet wordt als je niet ingezoomd bent.
    var passend: Passend = .scherm
    /// Staat er nu ingezoomd? De lezer zet daarop het bladeren uit, zodat je
    /// binnen de plaat kunt slepen in plaats van naar de volgende te schieten.
    var ingezoomd: Binding<Bool>?
    /// Wat een dubbeltik doet. Is dit gezet, dan wisselt de lezer van stand in
    /// plaats van in te zoomen op dat punt — knijpen blijft gewoon werken, dus
    /// je verliest er geen zoom mee.
    var opDubbeltik: (() -> Void)?

    func makeUIView(context: Context) -> UIScrollView {
        let scroll = UIScrollView()
        scroll.delegate = context.coordinator
        scroll.minimumZoomScale = 1
        scroll.maximumZoomScale = 4
        scroll.showsHorizontalScrollIndicator = false
        scroll.showsVerticalScrollIndicator = false
        scroll.backgroundColor = .clear
        scroll.contentInsetAdjustmentBehavior = .never
        scroll.bouncesZoom = true
        scroll.bounces = false
        scroll.alwaysBounceHorizontal = false
        scroll.alwaysBounceVertical = false
        // Op schaal 1 helemaal niet scrollen. Dat is wat de veeg naar de pager
        // eronder laat gaan: een scrollview met `isScrollEnabled` aan claimt de
        // pan óók als er niets te scrollen valt, en dan blader je niet meer.
        // Knijpen blijft wel werken — dat is een eigen gebaar dat hier niet aan
        // hangt. Zodra je ingezoomd bent gaat hij aan en sleep je binnen de
        // plaat, terwijl de pager juist uit staat.
        scroll.isScrollEnabled = false

        let weergave = UIImageView(image: beeld)
        weergave.contentMode = passend.contentMode
        weergave.clipsToBounds = true
        weergave.isUserInteractionEnabled = true
        weergave.translatesAutoresizingMaskIntoConstraints = false
        scroll.addSubview(weergave)
        context.coordinator.beeldweergave = weergave

        // Met constraints en niet met een frame in `updateUIView`. Dat laatste
        // leek te werken maar gaf een zwarte pagina op het toestel: bij de
        // eerste opbouw is `scroll.bounds` nog nul, de beeldweergave krijgt dan
        // een maat van nul, en er komt geen tweede aanroep meer zodra de
        // scrollview zijn echte maat krijgt. Vastgezet aan de frameLayoutGuide
        // groeit hij vanzelf mee.
        NSLayoutConstraint.activate([
            weergave.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor),
            weergave.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor),
            weergave.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor),
            weergave.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor),
            weergave.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor),
            weergave.heightAnchor.constraint(equalTo: scroll.frameLayoutGuide.heightAnchor),
        ])

        let dubbeltik = UITapGestureRecognizer(
            target: context.coordinator,
            action: #selector(Coordinator.dubbeltik(_:))
        )
        dubbeltik.numberOfTapsRequired = 2
        scroll.addGestureRecognizer(dubbeltik)

        return scroll
    }

    func updateUIView(_ scroll: UIScrollView, context: Context) {
        guard let weergave = context.coordinator.beeldweergave else { return }
        context.coordinator.ingezoomd = ingezoomd
        context.coordinator.opDubbeltik = opDubbeltik
        if weergave.image !== beeld {
            weergave.image = beeld
            // Terug naar volledig beeld: een nieuwe pagina hoort niet ingezoomd
            // te beginnen op de plek waar je de vorige had uitvergroot.
            scroll.setZoomScale(1, animated: false)
            scroll.isScrollEnabled = false
            ingezoomd?.wrappedValue = false
        }
        if weergave.contentMode != passend.contentMode {
            weergave.contentMode = passend.contentMode
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, UIScrollViewDelegate {
        var beeldweergave: UIImageView?
        var ingezoomd: Binding<Bool>?
        var opDubbeltik: (() -> Void)?

        func viewForZooming(in scrollView: UIScrollView) -> UIView? { beeldweergave }

        /// De lezer moet weten wanneer je ingezoomd bent, want dan hoort
        /// bladeren uit te staan — anders schiet je naar de volgende pagina
        /// terwijl je binnen deze wilt slepen.
        func scrollViewDidZoom(_ scrollView: UIScrollView) {
            let nu = scrollView.zoomScale > scrollView.minimumZoomScale + 0.01
            scrollView.isScrollEnabled = nu
            if ingezoomd?.wrappedValue != nu {
                ingezoomd?.wrappedValue = nu
            }
        }

        @objc func dubbeltik(_ gebaar: UITapGestureRecognizer) {
            guard let scroll = gebaar.view as? UIScrollView else { return }
            // Alleen als je niet ingezoomd bent: ben je dat wel, dan wil je met
            // een dubbeltik terug naar volledig beeld en niet van stand
            // wisselen.
            if let opDubbeltik, scroll.zoomScale <= scroll.minimumZoomScale + 0.01 {
                opDubbeltik()
                return
            }
            if scroll.zoomScale > scroll.minimumZoomScale {
                scroll.setZoomScale(scroll.minimumZoomScale, animated: true)
            } else {
                // Inzoomen op waar je tikt, niet op het midden: bij een strip
                // tik je op het paneel dat je wilt lezen.
                let punt = gebaar.location(in: beeldweergave)
                let schaal = min(scroll.maximumZoomScale, 2.5)
                let breedte = scroll.bounds.width / schaal
                let hoogte = scroll.bounds.height / schaal
                scroll.zoom(
                    to: CGRect(
                        x: punt.x - breedte / 2,
                        y: punt.y - hoogte / 2,
                        width: breedte,
                        height: hoogte
                    ),
                    animated: true
                )
            }
        }
    }
}
