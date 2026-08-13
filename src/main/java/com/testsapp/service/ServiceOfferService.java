package com.testsapp.service;
import com.testsapp.domain.ServiceOffer;
import com.testsapp.dto.CreateServiceOfferRequest;
import com.testsapp.dto.ServiceOfferResponse;
import com.testsapp.exception.ApiException;
import com.testsapp.repository.AppointmentRepository;
import com.testsapp.repository.ServiceOfferRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import java.math.BigDecimal;
import java.util.List;
@Service
public class ServiceOfferService {
    private final ServiceOfferRepository serviceOfferRepository;
    private final AppointmentRepository appointmentRepository;
    public ServiceOfferService(ServiceOfferRepository serviceOfferRepository, AppointmentRepository appointmentRepository) {
        this.serviceOfferRepository = serviceOfferRepository;
        this.appointmentRepository = appointmentRepository;
    }
    public List<ServiceOfferResponse> listAll() {
        return serviceOfferRepository.findAll().stream().map(this::toResponse).toList();
    }
    public List<ServiceOfferResponse> listActive() {
        return serviceOfferRepository.findActive().stream().map(this::toResponse).toList();
    }
    public ServiceOfferResponse create(CreateServiceOfferRequest request) {
        validateRequest(request);
        if (serviceOfferRepository.existsByNameIgnoreCase(request.name())) {
            throw new ApiException(HttpStatus.CONFLICT, "Usługa o takiej nazwie już istnieje.");
        }
        ServiceOffer saved = serviceOfferRepository.save(new ServiceOffer(
                normalizeName(request.name()),
                request.durationMinutes(),
                normalizePrice(request.basePrice()),
                true
        ));
        return toResponse(saved);
    }
    public ServiceOfferResponse activate(long id) {
        ServiceOffer offer = getOfferOrThrow(id);
        offer.activate();
        serviceOfferRepository.save(offer);
        return toResponse(offer);
    }
    public ServiceOfferResponse deactivate(long id) {
        ServiceOffer offer = getOfferOrThrow(id);
        if (!appointmentRepository.findFutureActiveByService(id, java.time.LocalDateTime.now()).isEmpty()) {
            throw new ApiException(HttpStatus.CONFLICT, "Nie można wyłączyć usługi z aktywnymi przyszłymi wizytami.");
        }
        offer.deactivate();
        serviceOfferRepository.save(offer);
        return toResponse(offer);
    }
    public ServiceOfferResponse getById(long id) {
        return toResponse(getOfferOrThrow(id));
    }
    private ServiceOffer getOfferOrThrow(long id) {
        return serviceOfferRepository.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono usługi o id=" + id));
    }
    private void validateRequest(CreateServiceOfferRequest request) {
        if (request == null) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Brak danych usługi.");
        }
        if (request.name() == null || request.name().isBlank()) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Nazwa usługi jest wymagana.");
        }
        if (request.durationMinutes() < 15 || request.durationMinutes() > 240 || request.durationMinutes() % 15 != 0) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Czas trwania musi byc wielokrotnoscia 15 minut, w zakresie 15-240.");
        }
        if (request.basePrice() == null || request.basePrice().compareTo(BigDecimal.ZERO) <= 0) {
            throw new ApiException(HttpStatus.BAD_REQUEST, "Cena bazowa musi byc wieksza od zera.");
        }
    }
    private String normalizeName(String name) {
        return name.trim();
    }
    private BigDecimal normalizePrice(BigDecimal price) {
        return price.setScale(2, java.math.RoundingMode.HALF_UP);
    }
    private ServiceOfferResponse toResponse(ServiceOffer offer) {
        return new ServiceOfferResponse(
                offer.getId(),
                offer.getName(),
                offer.getDurationMinutes(),
                offer.getBasePrice(),
                offer.isActive(),
                offer.getCreatedAt(),
                offer.getUpdatedAt()
        );
    }
}
