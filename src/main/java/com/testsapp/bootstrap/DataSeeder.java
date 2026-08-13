package com.testsapp.bootstrap;
import com.testsapp.domain.ServiceOffer;
import com.testsapp.repository.ServiceOfferRepository;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;
import java.math.BigDecimal;
@Component
public class DataSeeder implements CommandLineRunner {
    private final ServiceOfferRepository serviceOfferRepository;
    public DataSeeder(ServiceOfferRepository serviceOfferRepository) {
        this.serviceOfferRepository = serviceOfferRepository;
    }
    @Override
    public void run(String... args) {
        if (!serviceOfferRepository.findAll().isEmpty()) {
            return;
        }
        serviceOfferRepository.save(new ServiceOffer("Konsultacja wstepna", 30, new BigDecimal("120.00"), true));
        serviceOfferRepository.save(new ServiceOffer("Wizyta kontrolna", 15, new BigDecimal("80.00"), true));
        serviceOfferRepository.save(new ServiceOffer("Dluzsza konsultacja", 60, new BigDecimal("220.00"), true));
        serviceOfferRepository.save(new ServiceOffer("Pakiet rodzinny", 90, new BigDecimal("330.00"), false));
    }
}
